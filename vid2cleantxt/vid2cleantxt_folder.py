"""
vid2clntext by Peter Szemraj
Pipeline for Zero-shot transcription of a lecture video file to text using facebook's wav2vec2 model
This script is the 'folder' edition

large model link / doc from host website (huggingface)
https://huggingface.co/facebook/wav2vec2-large-960h-lv60-self

sections in this file:
- define model parameters (pretrained model)
- basic user inputs (vid file name / directory)
- convert video to audio chunks of duration X*
- pass all X audio chunks through wav2vec2model, store results in a list
- write all results of the list into a text file, store various runtime metrics
- pass created textfile through a spell checker and autocorrect spelling. save as new file
- run basic keyword extraction from (via YAKE) on spell-corrected file, save in the same directory as other results
- cleanup tasks (delete the X .wav files created for audio transcription, etc), report runtime, and exit

* (where X is some duration that does not overload your computer or crash your IDE)
"""

import math
import os
import shutil
import time
from datetime import datetime
from os import listdir
from os.path import isfile
from os.path import join

import librosa
import pandas as pd
import pysbd
import torch
from natsort import natsorted
from tqdm.auto import tqdm
from transformers import Wav2Vec2ForCTC, Wav2Vec2Tokenizer

from audio2text_functions import beautify_filename, convert_vid_for_transcription, create_folder, digest_text_fn, \
    quick_keys, shorten_title, symspell_file


# -------------------------------------------------------
# Function Definitions
# -------------------------------------------------------

def transcribe_video_wav2vec(transcription_model, directory, vid_clip_name, chunk_length_seconds, verbose=False):
    # this is the same process as used in the single video transcription, now as a function. Note that spell correction
    # and keyword extraction are now done separately in the script
    # user needs to pass in: the model, the folder the video is in, and the name of the video
    output_path_full = directory
    # Split Video into Audio Chunks-----------------------------------------------

    # create audio chunk folder
    output_folder_name = "audio_chunks"
    if not os.path.isdir(join(directory, output_folder_name)):
        os.mkdir(join(directory, output_folder_name))  # make a place to store outputs if one does not exist
    path2audiochunks = join(directory, output_folder_name)
    chunk_directory = convert_vid_for_transcription(vid2beconv=vid_clip_name, input_directory=directory,
                                                    len_chunks=chunk_length_seconds,
                                                    output_directory=path2audiochunks)

    full_transcription = []
    header = "Transcription of " + vid_clip_name + " at: " + \
             datetime.now().strftime("date_%d_%m_%Y_time_%H-%M-%S")
    full_transcription.append(header + "\n")
    before_loop_st = time.time()
    update_incr = math.ceil(len(chunk_directory) / 10)
    # Load audio chunks by name, pass into model, append output text-----------------------------------------------
    for audio_chunk in tqdm(chunk_directory, total=len(chunk_directory),
                            desc="Transcribing {}".format(shorten_title(vid_clip_name))):
        current_loc = chunk_directory.index(audio_chunk)

        audio_input, rate = librosa.load(join(path2audiochunks, audio_chunk), sr=16000)
        input_values = tokenizer(audio_input, return_tensors="pt", padding="longest",
                                 truncation=True).input_values
        logits = transcription_model(input_values).logits
        predicted_ids = torch.argmax(logits, dim=-1)
        transcription = tokenizer.batch_decode(predicted_ids)[0]
        full_transcription.append(transcription + "\n")

    if verbose: print("\nFinished audio transcription of " + vid_clip_name + " and now saving metrics.")

    # build metadata log -------------------------------------------------
    mdata = []
    mdata.append('original file name: ' + vid_clip_name + '\n')
    mdata.append(
        'number of recorded audio chunks: ' + str(len(chunk_directory)) + " of lengths seconds each" + str(
            chunk_length_seconds) + '\n')
    approx_input_len = (len(chunk_directory) * chunk_length_seconds) / 60
    mdata.append('approx {0:3f}'.format(approx_input_len) + ' minutes of input audio \n')
    mdata.append('transcription date: ' + datetime.now().strftime("date_%d_%m_%Y_time_%H-%M-%S") + '\n')
    full_text = ' '.join(full_transcription)
    transcript_length = len(full_text)
    mdata.append("length of transcribed text: " + str(transcript_length) + ' characters \n')
    t_word_count = len(full_text.split(' '))
    mdata.append("total word count: " + str(t_word_count) + ' words (based on spaces) \n')

    # delete audio chunks in folder -------------------------------------------------
    try:
        shutil.rmtree(path2audiochunks)
        if verbose: print("\nDeleted Audio Chunk Folder + Files")
    except:
        print("WARNING - unable to remove the folder {} containingg .WAV files")

    # compile results -------------------------------------------------
    transcription_results = {
        "audio_transcription": full_transcription,
        "metadata": mdata
    }
    if verbose: print("\nFinished transcription successfully for " + vid_clip_name + " at "
                      + datetime.now().strftime("date_%d_%m_%Y_time_%H-%M-%S"))

    return transcription_results


def validate_output_directories(directory):
    t_folder_name = "w2v2_video_transcriptions"
    m_folder_name = "w2v2_transcription_metadata"

    t_path_full = join(directory, t_folder_name)
    create_folder(t_path_full)

    m_path_full = join(directory, m_folder_name)
    create_folder(m_path_full)

    output_locs = {
        "t_out": t_path_full,
        "m_out": m_path_full
    }
    return output_locs


# -------------------------------------------------------
# Main Script
# -------------------------------------------------------

if __name__ == "__main__":
    # start tracking rt
    st = time.time()

    # load pretrained model
    # if running for first time on local machine, start with "facebook/wav2vec2-base-960h" for both tokenizer and model
    wav2vec2_model = "facebook/wav2vec2-large-960h-lv60-self"  # tested up to 35 second chunks
    # wav2vec2_model = "facebook/wav2vec2-base-960h" # tested up to 90 second chunks. Faster, but less accurate
    print("\nPreparing to load model: " + wav2vec2_model + " - ", datetime.now())
    tokenizer = Wav2Vec2Tokenizer.from_pretrained(wav2vec2_model)
    model = Wav2Vec2ForCTC.from_pretrained(wav2vec2_model)
    chunk_length = 30  # (in seconds) if model fails to work or errors out (and there isn't some other
    # obvious error, reduce this number.

    # Ask user for folder
    directory = str(input("\n Enter full path to directory containing videos ---->"))
    tr_db_name = 'runtime data for of ' + ''.join(ch for ch in directory if ch.isalnum()) + " transcription.xlsx"

    # iterate through directory and get list of only video files --------------------------------------------------

    files_to_munch = natsorted([f for f in listdir(directory) if isfile(join(directory, f))])
    total_files_1 = len(files_to_munch)
    removed_count_1 = 0
    approved_files = []
    # remove non-.txt files
    for prefile in files_to_munch:
        if prefile.endswith(".mp4") or prefile.endswith(".mov") or prefile.endswith(".avi"):
            approved_files.append(prefile)
        else:
            files_to_munch.remove(prefile)
            removed_count_1 += 1

    print(
        "\nFrom {} file(s) originally in the folder, {} non-video files removed".format(total_files_1, removed_count_1))
    print('{} file(s) in folder will be transcribed.\n'.format(len(approved_files)))

    # iterate through list of video files, transcribing one at a time --------------------------------------------------
    storage_locs = validate_output_directories(directory)  # create and get output folders
    out_p_tscript = storage_locs.get('t_out')
    out_p_metadata = storage_locs.get('m_out')

    for filename in tqdm(approved_files, total=len(approved_files), desc="transcribing video files from folder"):
        # transcribe the video file
        t_results = transcribe_video_wav2vec(transcription_model=model, directory=directory,
                                             vid_clip_name=filename, chunk_length_seconds=chunk_length)
        full_transcription = t_results.get('audio_transcription')
        metadata = t_results.get('metadata')

        # label and store this transcription
        vid_preamble = beautify_filename(filename, num_words=15,
                                         start_reverse=False)  # gets a nice phrase from filename
        # transcription
        transcribed_filename = vid_preamble + '_tscript_' + datetime.now().strftime("_%H.%M.%S") + '.txt'
        transcribed_file = open(join(out_p_tscript, transcribed_filename), 'w', encoding="utf-8", errors='ignore')
        with open(join(out_p_tscript, transcribed_filename), 'w', encoding="utf-8", errors='ignore') as tf:
            tf.writelines(full_transcription)  # save transcription

        metadata_filename = 'metadata for ' + vid_preamble + " transcription.txt"
        with open(join(out_p_metadata, metadata_filename), 'w', encoding="utf-8", errors='ignore') as md:
            md.writelines(metadata)  # save metadata

    # ----------------------------------- Merge Text Files  -------------------------------
    # makes things easier to review when you only have to open one file instead of N

    pr_stamp = datetime.now().strftime("date_%d_%m_%Y_time_%H")
    digest_text_fn(out_p_tscript, iden="original_tscripts" + pr_stamp, w_folder=True)
    digest_text_fn(out_p_metadata, iden="metadata_for_tscript_run" + pr_stamp)

    # ----------------------------------- Improve Base Transcriptions  -------------------------------
    # iterate through list of transcribed files, correcting spelling and generating keywords

    # first, you need to go through the output directory of transcripts and make sure that all those files are gucci
    transcripts_to_munch = natsorted(
        [f for f in listdir(out_p_tscript) if isfile(join(out_p_tscript, f))])
    t_files = len(transcripts_to_munch)
    removed_count_t = 0
    # remove non-.txt files
    for tfile in transcripts_to_munch:
        if tfile.endswith(".txt"):
            continue
        else:
            transcripts_to_munch.remove(tfile)
            removed_count_t += 1

    print("from {} file(s) originally in the folder, {} non-txt files removed".format(t_files, removed_count_t))

    # Go through base transcription files and spell correct them and get keywords
    seg = pysbd.Segmenter(language="en", clean=True)  # loads pySBD
    keyphrase_df_transc = pd.DataFrame()
    kp_fname = "YAKE_keywords_for_all_transcr.xlsx"
    for textfile in tqdm(transcripts_to_munch, total=len(transcripts_to_munch), desc="Spell Correct & Keywords"):
        tf_pretty_name = beautify_filename(textfile, start_reverse=False, num_words=10)

        # auto-correct spelling (wav2vec2 doesn't enforce spelling on its output)
        corr_results_fl = symspell_file(filepath=out_p_tscript, filename=textfile, keep_numb_words=True,
                                        want_folder=True, dist=2)
        output_path_impr = corr_results_fl.get("output_path")

        # Write version of transcription with sentences / boundaries inferred with periods. All text in one line
        seg_list = seg.segment(corr_results_fl.get("corrected_ssp_text"))
        seg_text = '. '.join(seg_list)
        seg_outname = "SegTEXT " + tf_pretty_name + ".txt"
        with open(join(output_path_impr, seg_outname), 'w', encoding="utf-8", errors='ignore') as fs:
            fs.write(seg_text)

        # extract keywords from transcription (once spell-corrected)
        key_phr_fl = quick_keys(filepath=output_path_impr, filename=corr_results_fl.get("corrected_ssp_fname"),
                                num_keywords=50, max_ngrams=3, save_db=False)

        # edit returned keyword dataframe from quick_keys() and append to total one
        db_col_name = ''.join(list([val for val in tf_pretty_name if val.isalnum()]))
        key_phr_fl.drop(key_phr_fl.columns[[1, 2]], axis=1, inplace=True)
        key_phr_fl.columns = ["YAKE_keywords_from_" + db_col_name, "freq_of_kw_in_" + db_col_name]

        if transcripts_to_munch.index(textfile) == 0:
            # on first iteration set blank df equal to keyword df from first file
            keyphrase_df_transc = key_phr_fl
        else:
            # update the dataframe adding columns on the right (colnames should be unique from manual naming above)
            keyphrase_df_transc = pd.concat([keyphrase_df_transc, key_phr_fl], axis=1)

        # save & overwrite each iteration
        keyphrase_df_transc.to_excel(join(out_p_tscript, kp_fname))

    # ----------------------------------- END -------------------------------
    print("\n\n----------------------------------- Script Complete -------------------------------")
    print("Transcription files + more in folder: \n", out_p_tscript)
    print("Metadata for each transcription located @ \n", out_p_metadata)
    # save runtime database one last time
    print("total runtime was {} minutes".format(round((time.time() - st) / 60), 2))
