# Detailed Information about the Project

This document explains the project in depth: what every screen of the app shows, and what every file in the code does.
For setup and a quick overview, see the [README](README.md).

**Contents**
1. [UI Explanation](#1-ui-explanation) - a walkthrough of every screen, with screenshots
   - [1.1 Translate](#11-translate)
   - [1.2 Conversation](#12-conversation)
   - [1.3 Summarize](#13-summarize)
   - [1.4 Under the hood](#14-under-the-hood)
   - [1.5 Benchmark](#15-benchmark)
   - [1.6 Add my voice](#16-add-my-voice)
2. [Files](#2-files) - what each file in the project is for

---

## 1. UI Explanation

The app is a single web page served by the local Python server. The top bar has five tabs - **Translate**,
**Conversation**, **Summarize**, **Under the hood** and **Benchmark** - and on the right a status line showing which
models are loaded (here: *Whisper large-v3-turbo · GPU · gemma4:e2b*). The green dot means everything is ready.

### 1.1 Translate

#### The main screen
![Translate tab](ASR%20Project%20Screenshots/Screenshot%202026-11-15%20182151.png)

This is the home screen. From top to bottom:
- **I'm speaking / Translate to** - the spoken language (or *Auto-detect*) and the language you want to hear. The ⇄ button swaps them.
- **Voice, Speed, Pitch** - which neural voice reads the translation (here *Madhur · Male*), how fast and how high. The ▶ button previews the voice. **+ Add my voice** opens the voice-cloning studio.
- **The microphone** - click it or press **Space** to record; a live waveform shows while you speak. You can also upload an audio file.
- **The four-step tracker** - *Clean audio → Recognize → Translate → Speak*, each with the time it took
  (242 ms, 1.2 s, 556 ms, 1.2 s). "See every calculation behind this" jumps to the *Under the hood* tab.

#### The result
![Translation result](ASR%20Project%20Screenshots/Screenshot%202026-11-15%20182233.png)

After speaking *"Hi, I am Rajveer and I am from Kolkata, the city of joy."*:
- **What you said** - Whisper's transcript, the detected language with its certainty (*English · 100%*), and an overall
  **confidence** bar (89%). Words Whisper was unsure about are highlighted in yellow; **Edit** lets you correct them and re-translate.
- **Translation** - the Hindi translation, which appears word by word as the local AI writes it, plus a player to hear it
  (voice: *Madhur · Edge neural TTS*), a download button and a copy button.

#### Choosing languages
| Target language | Spoken language |
|---|---|
| ![Translate-to list](ASR%20Project%20Screenshots/Screenshot%202026-11-15%20182254.png) | ![I'm-speaking list](ASR%20Project%20Screenshots/Screenshot%202026-11-15%20182310.png) |

The app supports **22 languages**, including ten Indian languages (Hindi, Bengali, Tamil, Telugu, Marathi, Gujarati,
Kannada, Malayalam, Urdu) as well as English, Spanish, French, German, Italian, Portuguese, Russian, Japanese, Korean,
Chinese, Arabic, Turkish and Dutch. For the spoken language you can choose **Auto-detect**, and Whisper works out the language by itself.

### 1.2 Conversation

#### Setting up two people
![Conversation setup](ASR%20Project%20Screenshots/Screenshot%202026-11-15%20182431.png)

For two people who don't share a language. **Person A** speaks Hindi, **Person B** speaks English. For each person you
choose the voice their words are spoken in *after translation* (A's Hindi is spoken in English by *Eric*; B's English is
spoken in Hindi by *Swara*).

In **Push to talk** mode, each person has a button: press it, speak, press it again. Because each person has their own
button, the app always knows who is talking - the most reliable mode in noisy places.

#### Choosing a voice
![Voice list](ASR%20Project%20Screenshots/Screenshot%202026-11-15%20182459.png)

Each language has many male and female neural voices with different accents (US, UK, Indian, Australian…), such as
*Natasha*, *Ryan*, *Neerja* or *Prabhat*. If you have cloned your own voice, it also appears here, so your words can be
spoken **in your own voice** in the other language.

#### Hands-free mode
![Hands-free listening](ASR%20Project%20Screenshots/Screenshot%202026-11-15%20182612.png)

No buttons: just talk. A **voice-activity detector running in the browser** listens continuously:
- the bar shows the current loudness (*-54 dB*), the grey mark is the learned **noise floor** of the room (*-60*) and the red mark is the **trigger** level (*-48*);
- when someone speaks louder than the trigger, recording starts (keeping the 0.3 s before it, so the first syllable isn't lost);
- after 0.9 s of silence the turn ends and is sent for translation;
- listening pauses while the translation plays, so the app doesn't translate its own voice.

#### A real conversation
![Conversation result](ASR%20Project%20Screenshots/Screenshot%202026-11-15%20183118.png)

A tourist (Person B, English) asks for help; a local (Person A, Hindi) answers. Each bubble shows:
- who spoke and the direction (*Person A · Hindi → English*);
- in hands-free mode, **which language was detected** and how sure Whisper was (*detected Hindi 99% vs English 1%*) - Whisper only has to choose between the two languages of the conversation;
- the original words (small) and the translation (large), a ▶ button to replay it, the voice used and the total time (about 3.5-5 s per turn).

**Export** saves the whole conversation as a text file; **Clear** starts over.

### 1.3 Summarize

#### Choosing a recording
![Summarize input](ASR%20Project%20Screenshots/Screenshot%202026-11-15%20183150.png)

For long recordings - lectures, meetings, podcasts, voice notes and even **videos**. Drop a file in (here a 1:56 screen
recording, 98 MB MP4) or **Record live** with no time limit. Options: the spoken language, the language the summary is
written in, and whether to read the TL;DR aloud (optionally **in my own voice**).

#### Processing
![Summarize progress](ASR%20Project%20Screenshots/Screenshot%202026-11-15%20183208.png)

Four steps, each with a short explanation and its time:
1. **Prepare audio** - the audio is pulled out of the video and cleaned (*1:56 of audio decoded and cleaned, 401 ms*).
2. **Transcribe** - Whisper writes the transcript, which fills in live below with timestamps (*302 words · 20 segments · 12.1× faster than real time*).
3. **Summarize** - the local AI summarises the transcript in parts (*map: 3 chunks of ~120 words*), then combines them.
4. **Read aloud** - the TL;DR is spoken by a neural voice.

#### The summary
![Summary result](ASR%20Project%20Screenshots/Screenshot%202026-11-15%20183233.png)

- **Export buttons** - Markdown (summary + transcript), plain-text transcript, or **.srt subtitles**.
- **Player** - the original recording.
- **TL;DR** - a 2-3 sentence gist, with **Listen** to hear it.
- **Key points** - the most important points.
- **Action items** - tasks and commitments as a checklist (none were mentioned in this recording, and the app says so instead of inventing some).

#### Chapters and transcript
![Chapters and transcript](ASR%20Project%20Screenshots/Screenshot%202026-11-15%20183246.png)

- **Chapters** - the recording split into topics with start times (*0:00, 0:41, 1:27*). Click one to jump there in the player; the current chapter is highlighted while it plays.
- **How this summary was made** - expands to show the two-round ("map-reduce") process and each part's notes.
- **Transcript** - every segment with its timestamp, searchable. Click a line to play from that moment; the current line is highlighted during playback.

### 1.4 Under the hood

This tab shows **every calculation** behind the last recording. Nothing is a mock-up: all charts and numbers are computed live.

#### Timeline and waveform
![Under the hood - overview](ASR%20Project%20Screenshots/Screenshot%202026-11-15%20183403.png)

- **Where the time went** - a bar showing how long each stage took: cleaning, log-Mel features, Whisper decoding (1.16 s), LLM translation (556 ms) and speech synthesis (1.20 s).
- **Replay decoding** - re-plays the decoding animation (below) using the real tokens and timings.
- **Waveform: raw vs cleaned** - your recording before and after our cleaning. The grey areas at the edges are silence that gets trimmed away.

#### Cleaning the audio
![Under the hood - cleaning](ASR%20Project%20Screenshots/Screenshot%202026-11-15%20183421.png)

- **Frequency content & the high-pass filter** - energy at each frequency before (grey) and after (purple) the filter. The dashed orange line is the filter itself: it removes everything below **80 Hz** (fan hum, desk thumps), which is below the lowest human voice.
- **Voice activity detection** - the recording is cut into 30 ms frames (194 here); green frames are speech, grey are silence. The red line is the **speech threshold**, the dashed line the **noise floor**.
- **Formulas** - exactly how loudness, noise floor, threshold and gain are calculated.
- **Numbers** - e.g. noise floor -50 dBFS, speech level -22.5 dBFS, **signal-to-noise 27.5 dB** (green = good), 144 of 194 frames were speech, no clipping, and the whole front-end took 242 ms.

#### The log-Mel spectrogram
![Under the hood - log-Mel](ASR%20Project%20Screenshots/Screenshot%202026-11-15%20183507.png)

Neural networks don't hear; they see numbers. Whisper converts sound into a **log-Mel spectrogram**, a picture of which
pitches are present at each moment. This section computes it step by step:
- **The chain of steps** - 89,120 audio samples → 25 ms frames every 10 ms → Hann window → FFT (558 × 201) → 128 Mel bands → log → scaling → padding to 30 s.
- **One frame's journey** - the loudest 25 ms slice shown at each step: (a) the raw samples with the window shape, (b) its frequencies after the FFT, (c) the Mel filters, which are narrow at low pitch and wide at high pitch, like the human ear, (d) the final 128 numbers Whisper reads.
- **The full spectrogram** - time left to right, pitch bottom to top, brightness = energy, with the recognised words placed where Whisper heard them.
- **Matches Whisper's code: ✓ identical** - our own implementation produces exactly the same numbers as Whisper's (difference 0).

#### Language detection
![Under the hood - spectrogram and language](ASR%20Project%20Screenshots/Screenshot%202026-11-15%20183611.png)

Before writing anything, Whisper scores all **100 languages** it knows. The bars show the top candidates: here
**English 99.7%**, with German, Chinese, Japanese and the rest close to 0%.

#### Decoding: sound → tokens → words
![Under the hood - decoding](ASR%20Project%20Screenshots/Screenshot%202026-11-15%20183624.png)

- **Tokens the model produced** - Whisper writes text in *tokens* (words or word-pieces) from a vocabulary of 51,866, each with its ID number. Special tokens tell it the task (*startoftranscript, en, transcribe … endoftext*). Notice "Rajveer" is split into *Raj* + *veer* and "Kolkata" into *Kol* + *k* + *ata*, because those names aren't single tokens in its vocabulary.
- **Words, timings and probabilities** - each word with when it was spoken and how sure Whisper was. Words below 60% would be highlighted for checking; *joy* (67%) and *city* (74%) were the least certain here.
- **Quality checks per segment** - average log-probability, **compression ratio** (above 2.4 would mean repetitive gibberish, so Whisper retries), **no-speech probability**, and the sampling temperature used.

#### Translation by the local AI
![Under the hood - translation](ASR%20Project%20Screenshots/Screenshot%202026-11-15%20183641.png)

- **Prompt sent to the model** - the exact instructions (*system*) and your words (*user*) sent to **gemma4:e2b** running on the GPU through Ollama. The instructions include the rules that keep pronouns correct ("you" stays "you") and stop the model from answering instead of translating.
- **Model output (live)** - the translation as it was generated.
- **Stats** - 189 prompt tokens read, 17 tokens generated at **106 tokens per second**, temperature 0 (the same sentence always gets the same translation).

#### Speech synthesis
![Under the hood - speech](ASR%20Project%20Screenshots/Screenshot%202026-11-15%20183654.png)

The waveform of the generated speech, and its details: engine (*Edge neural TTS*), voice (*Madhur*), 58 characters in,
5.57 s of audio out, speed and pitch, synthesis time 1.20 s and a **real-time factor of 0.21×**, i.e. it was produced
about 5× faster than it takes to play.

### 1.5 Benchmark

This tab measures **how accurate the speech recognition is on your own voice**.

#### Recording a test set
![Benchmark - recording](ASR%20Project%20Screenshots/Screenshot%202026-11-15%20183736.png)

You read sentences whose exact text is known (40 in English, 20 in Hindi), so the app can later compare what you
*said* with what each model *heard*. Here all **40 English sentences** are recorded (132 s of audio). Use **Space** to
record or stop, and the arrow keys to move between sentences. The recordings stay on your computer and are never uploaded to GitHub.

The three measures used: **WER** (% of words wrong, lower is better), **CER** (% of characters wrong) and **RTF**
(processing time ÷ audio length; 0.1 means 10× faster than real time).

#### Running the benchmark
![Benchmark - run](ASR%20Project%20Screenshots/Screenshot%202026-11-15%20183747.png)

Pick which Whisper models to compare - *tiny* (75 MB), *small* (0.5 GB), *medium* (1.5 GB), *large-v3-turbo* (1.6 GB,
the app default) - and whether to compare **with and without our audio cleaning**. Every selected model transcribes
every recording; models not used before are downloaded once.

#### Results
![Benchmark - results](ASR%20Project%20Screenshots/Screenshot%202026-11-15%20183803.png)

- **Warning box** - flags differences too small to be meaningful (here, cleaning vs raw differed by 0-1 words for every model).
- **Results table** - for each model and cleaning setting: WER, the number of wrong words (substitutions / deletions / insertions out of 381), CER, speed, language-detection accuracy and average confidence. The best row is starred: **large-v3-turbo got 2 words wrong out of 381 (0.5% WER)**.
- **Word error rate by model** - blue = with our cleaning, orange = raw audio. *small* scored worst (5.3%) because it mistook two of the English sentences for Hindi.
- **Speed vs accuracy** - each dot is one configuration; bottom-left (fast and accurate) is best. Turbo sits there, which confirms it as the right default.

#### Confidence scores and hardest sentences
![Benchmark - calibration](ASR%20Project%20Screenshots/Screenshot%202026-11-15%20183836.png)

- **Can you trust the confidence scores?** - every word Whisper wrote is grouped by the confidence it gave, then checked against what was actually said. The dashed line is the app's 60% highlight threshold. With only 2 wrong words, there were too few mistakes to judge this, and the app says so.
- **Hardest sentences** - the sentences with the most mistakes, shown word by word (green = correct, yellow = substituted) with a ▶ button to listen to the recording. Here: *"send"* was heard as *"find"*, and *"the"* as *"this"*.

### 1.6 Add my voice

Opened with the **+ Add my voice** button on the Translate tab. It clones your voice so translations can be spoken in it.

#### Generating a reading script
![Add my voice - script](ASR%20Project%20Screenshots/Add%20my%20voice%201.png)

- **Your saved voices** - voices you've already recorded, with their details: the date, how much speech was used (31.2 s), how accurately the script was read (89%) and the background-noise level (SNR 21 dB). **Delete** removes the voice and its recording.
- **Voice name and script language** - the script can be read in **English or Hindi**. Either way, the cloned voice can then speak all 17 supported languages (English, Hindi, Spanish, French, German, Japanese, Chinese, Arabic and more); other languages fall back to a regular neural voice.
- **Generate script** - creates a new reading script. The tags above it summarise it: *9 lines · 85 words · ≈33 s to read*, covering **47 of 48 different sound patterns**, with statements, a question, an exclamation and numbers, so the model hears your full range of sounds and tones.

#### Recording
![Add my voice - recording](ASR%20Project%20Screenshots/Add%20my%20voice%202.png)

- **The script** - each line is labelled with its type (*statement, question, numbers, exclamation*). While you record, it works like a teleprompter: the current line is highlighted, and **Enter** or **Next line** moves to the next one.
- **Tips** - a quiet room, about a hand's width from the mic, and reading naturally.
- **Start recording / New script** - record, or get a different set of sentences.
- **Timer and progress bar** - marks for **10 s** (minimum), **20 s** (good) and **30 s** (ideal). The bar turns from red to yellow to green as you pass them, and a level meter warns you if you're too loud.

After you stop, the app checks the recording before using it: length, background noise, clipping, and whether you
actually read the script (measured with our own speech recognition, shown word by word). If the recording passes, it
builds your voice profile, plays a test sentence in your cloned voice and shows a **voice-similarity score**. A
recording that fails isn't saved.

---

## 2. Files

Generated audio, voice recordings and downloaded models are created while the app runs. They are listed at the end,
and they are never uploaded to GitHub.

### Root folder

**`server.py`** - The web server (FastAPI) and the program you start (`python server.py`). It serves the web page and
offers an API endpoint for each feature: translate, conversation turn, summary, voices, voice cloning and benchmark. On
startup it loads Whisper, Ollama and, if you have a saved voice, XTTS in the background so the first request is fast.
It also deletes generated audio older than 24 hours.

**`pipeline.py`** - Connects all the steps into complete jobs: clean audio → recognise → translate → speak, a
conversation turn (including deciding which of the two languages was spoken), long-recording summaries and voice
enrolment. Each step sends progress events with its timing, which is what makes the step trackers in the UI light up live.

**`config.py`** - Every setting in one place: Whisper model and device, audio-cleaning thresholds, the confidence
threshold for highlights, the Ollama model and context size, and the 22 languages with their default voices. Values that
differ between computers (models, port and so on) can be overridden in a `.env` file.

**`check_setup.py`** - A health check to run after installing (`python check_setup.py`). It confirms the conda env,
ffmpeg, the GPU (by actually running a small Whisper model on it), Ollama and its model, and that every language's
voice exists, and prints a clear fix for anything that's missing.

**`requirements.txt`** - The Python packages the core app needs (Whisper, audio maths, web server, Edge voices and so
on), with exact versions so the setup is reproducible.

**`requirements-voice.txt`** - The optional extra packages for speaking in your own voice: PyTorch with GPU support,
coqui-tts (XTTS-v2) and a few helpers it needs for Chinese and Japanese. It's kept separate because it's about 3 GB.
The file also explains how to uninstall it all again.

**`requirements-dev.txt`** - Only `pytest`, the tool that runs the automated tests.

**`.env.example`** - A template listing the settings you can change without editing code (Whisper model, Ollama
address and model, port, how long generated audio is kept). Copy it to `.env` to use it. The real `.env` is never
uploaded, so it is also the place for any secret keys in future.

**`.gitignore`** - Tells git which files must never be uploaded to GitHub: your voice recordings, benchmark recordings,
`.env`, generated audio, downloaded models and Python cache files.

**`README.md`** - The project's front page on GitHub: what it does, setup, how to run it, a screenshot gallery,
licences and known limitations.

**`LICENSE`** - The MIT licence for the code, plus a note that the AI models keep their own licences (XTTS-v2 is for
non-commercial use only).

**`Detailed-Information-about-the-Project.md`** - This document.

### `asr/` - speech recognition

**`asr/audio.py`** - Our audio front-end. It decodes any audio or video format with ffmpeg, removes the DC offset,
applies the 80 Hz high-pass filter, normalises the volume (capped at +30 dB so silence isn't blown up into noise),
detects speech frame by frame with an adaptive threshold, and trims the silence. It also returns all the measurements
and chart data shown on the *Under the hood* tab.

**`asr/features.py`** - Our own step-by-step implementation of the log-Mel spectrogram (framing, Hann window, FFT,
Mel filterbank, log, clamping, scaling). It checks itself against Whisper's own code (they match exactly) and prepares
the spectrogram and "one frame's journey" data for the UI.

**`asr/transcriber.py`** - Runs the Whisper model (faster-whisper) on the GPU, falling back to the CPU if needed. It
returns the text, the detected language with probabilities, every token, each word's confidence and the per-segment
quality checks. It can also detect a language among just two choices (for conversations) and stream segments one by
one for long recordings.

**`asr/metrics.py`** - The accuracy maths: WER and CER with word-by-word alignment. Before comparing, it normalises
harmless differences ("42" = "forty two", "7:20" or "9.30" = a time, "I'm" = "I am", Hindi spelling variants like पाँच/पांच),
so that only real mistakes are counted.

**`asr/gpu.py`** - A small Windows helper that makes the NVIDIA libraries installed by pip (cuBLAS, cuDNN) findable,
so Whisper can use the GPU.

**`asr/__init__.py`** - Marks `asr` as a Python package. The same applies to the `__init__.py` files in the other folders.

### `translation/` - translating text

**`translation/translator.py`** - Sends the transcript to the local AI model (gemma4:e2b via Ollama) and streams the
translation back word by word. Its instructions keep pronouns exactly as spoken and mark your words as *text to
translate*, never as commands. This fixed a real bug where "What is your name?" became "What is my name?".

### `tts/` - speech output and voice cloning

**`tts/speaker.py`** - Turns text into speech. It lists every Microsoft Edge neural voice for a language, applies speed
and pitch, and sends cloned-voice requests to XTTS. If your own voice can't be used (an unsupported language, a deleted
voice or an error), it falls back to a neural voice and explains why.

**`tts/cloner.py`** - Speaks in your own voice using XTTS-v2. It saves your cleaned reference recording, computes your
voice profile once (a speaker embedding plus style information), generates speech in 17 languages, and scores how
similar the clone sounds to you. It also spells out numbers in Hindi and Chinese, because XTTS crashes on digits in those languages.

**`tts/enroll.py`** - The voice-enrolment logic. It generates the ~30-second reading script, choosing sentences that
cover as many different speech sounds as possible plus a question, an exclamation and numbers. Afterwards it checks the
recording: length, background noise, clipping, and whether you read the script, measured with our own speech recognition.

### `summarize/` - long-recording summaries

**`summarize/summarizer.py`** - Summarises long transcripts in two rounds. First each chunk of a few minutes gets its own
title, notes and action items (these become the chapters); then the model combines those notes into the final TL;DR,
key points and action items. The chunk size adapts to the recording's length, and the model is asked for structured
(JSON) answers so the results are reliable.

### `eval/` - accuracy benchmark

**`eval/evaluate_wer.py`** - The benchmark engine. It holds the test sentences (40 English, 20 Hindi), stores your
recordings, runs every selected Whisper model with and without our cleaning, and calculates WER, CER, speed,
language-detection accuracy and how trustworthy the confidence scores are. It can also run from the terminal and
produce a Markdown table for the README.

### `static/` - the web page (runs in the browser)

**`static/index.html`** - The structure of the whole app: the top bar with tabs, and the content of every tab
(Translate, Conversation, Summarize, Under the hood, Benchmark) plus the "Add my voice" window.

**`static/style.css`** - The look of the app: colours (with automatic light and dark themes), layout, the step trackers,
chat bubbles, charts, and the phone-width layout.

**`static/app.js`** - The Translate tab and shared behaviour: tab switching, recording from the microphone with the live
waveform, sending audio to the server and reading the live progress, showing the transcript with highlighted words,
editing and re-translating, the voice/speed/pitch controls and the status indicator.

**`static/viz.js`** - Draws everything on the *Under the hood* tab: waveforms, the filter and frequency chart, the
VAD frames, the spectrogram heat-map with words, the language bars, the token and word replay animation, and the
translation and speech statistics. Plain canvas drawing, no chart library.

**`static/conversation.js`** - The Conversation tab. It captures raw microphone audio, runs the hands-free voice
detector (learning the room's noise level, keeping 0.3 s of pre-roll, ending a turn after 0.9 s of silence), encodes
WAV files, and shows each turn as a chat bubble with the detected language. It also handles push-to-talk and export.

**`static/summary.js`** - The Summarize tab: file drop and live recording, the progress steps with the live transcript
and time-left estimate, the results (TL;DR, key points, action items, chapters), the searchable transcript that follows
playback, and the Markdown / text / subtitle exports.

**`static/bench.js`** - The Benchmark tab: recording the test sentences, running the benchmark with a progress bar, the
results table, the accuracy and speed charts with hover tooltips, the confidence chart, the hardest-sentences list and
"Copy as Markdown".

**`static/voicelab.js`** - The "Add my voice" window: it generates the reading script, shows it as a teleprompter
while you record (with a level meter and a progress bar marking 10 s, 20 s and 30 s), then shows the quality checks,
the word-by-word comparison with the script, the test sentence in your cloned voice and its similarity score.

### `tests/` - automated tests

Small automatic checks (run with `pytest`) for the logic that doesn't need a GPU. They run on GitHub after every push.

**`tests/test_metrics.py`** - Checks the accuracy scoring: harmless differences (numbers, times, contractions, Hindi
spellings) are not counted as errors, real mistakes are, and Whisper's split words (like "5," + "000") are scored correctly.

**`tests/test_numbers.py`** - Checks that numbers are spelled out correctly for your cloned voice in Hindi
(42 → बयालीस, up to crores) and Chinese (105 → 一百零五), and that other languages are left unchanged.

**`tests/test_audio.py`** - Tests the audio cleaning on generated signals with known answers: the filter removes 30 Hz
rumble but keeps 300 Hz speech, normalisation hits its target and its +30 dB cap, the voice detector finds speech, and
silence-only recordings are rejected.

**`tests/test_enroll_and_summary.py`** - Checks that every generated reading script has all four sentence types and
about 30 seconds of text, that the recording checks pass and fail correctly, and that long transcripts are split into
sensible chunks.

**`tests/test_translator.py`** - Makes sure the translation rules that fixed the "your name → my name" bug can never be
accidentally removed.

**`tests/conftest.py`** - Shared setup that lets the tests import the project's code.

### Other folders

**`.github/workflows/tests.yml`** - Tells GitHub to install a light set of packages and run all the tests on every push.
This is what powers the green "tests" badge in the README.

**`ASR Project Screenshots/`** - The screenshots used in this document.

**`docs/screenshots/`** - The screenshots used in the README's gallery.

### Created while the app runs (never uploaded)

| Folder | What it holds |
|---|---|
| `outputs/` | Generated speech files; anything older than 24 h is deleted automatically. |
| `voices/` | Your cloned voices: your reference recording and voice profile. |
| `eval/datasets/` | Your benchmark recordings. |
| `eval/results/` | Saved benchmark results. |
| `models/` | coqui-tts housekeeping files (the XTTS model itself is stored in the Hugging Face cache). |
