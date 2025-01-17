import random
import numpy as np
import torch
import torch.utils.data
from resemblyzer import VoiceEncoder, preprocess_wav
from pathlib import Path

import layers
from utils import load_wav_to_torch, load_filepaths_and_text, load_filepaths_and_PPG
from text import text_to_sequence

class PPG_MelLoader(torch.utils.data.Dataset):
    """
        1) loads PPG, audio pairs.
        2) reads PPG.
        3) extract speaker_id_embedding from audio files.
        4) concatenate speaker_id_embedding and PPG
        5) computes mel-spectrograms from audio files.
        sample: meian/meian_0000.wav|PPG/PPG_0.npy
    """
    def __init__(self, audiopaths_and_PPG, hparams):
        # 这个时候audiopaths_and_PPG是一个列表套列表[[audiopaths,PPGpath],[audiopaths,PPGpath]...]
        # 其中audiopaths是音频路径，PPGpath是存储PPG的npy文件
        self.audiopaths_and_PPG = load_filepaths_and_PPG(audiopaths_and_PPG)
        
        self.max_wav_value = hparams.max_wav_value
        self.sampling_rate = hparams.sampling_rate
        self.load_mel_from_disk = hparams.load_mel_from_disk
        self.stft = layers.TacotronSTFT(
            hparams.filter_length, hparams.hop_length, hparams.win_length,
            hparams.n_mel_channels, hparams.sampling_rate, hparams.mel_fmin,
            hparams.mel_fmax)
        random.seed(hparams.seed)
        # shuffle一下，让原来按顺序读入变成乱序
        random.shuffle(self.audiopaths_and_PPG)

    def get_mel_PPG_pair(self, audiopath_and_PPG):
        # separate audiopath and PPG
        audiopath, PPG = audiopath_and_PPG[0], audiopath_and_PPG[1]
        
        # 拼接PPG和speaker_embedding
        speaker_embedding = self.get_id(audiopath)
        PPG = self.get_ppg(PPG, speaker_embedding)
        
        mel = self.get_mel(audiopath)
        return (PPG, mel)

    def get_id(self, audiopath):
        # 调用resemblyzer的VoiceEncoder做speaker embedding
        encoder = VoiceEncoder()
        fpath = Path(audiopath)
        wav = preprocess_wav(fpath)
        # 得到speaker embedding
        speaker_embedding = encoder.embed_utterance(wav)
        # 输出调试信息
        # np.set_printoptions(precision=3, suppress=True)
        # print(speaker_embedding)
        #
        return speaker_embedding
    
    def get_mel(self, filename):
        if not self.load_mel_from_disk:
            audio, sampling_rate = load_wav_to_torch(filename)
            if sampling_rate != self.stft.sampling_rate:
                raise ValueError("{} {} SR doesn't match target {} SR".format(
                    sampling_rate, self.stft.sampling_rate))
            audio_norm = audio / self.max_wav_value
            audio_norm = audio_norm.unsqueeze(0)
            audio_norm = torch.autograd.Variable(audio_norm, requires_grad=False)
            melspec = self.stft.mel_spectrogram(audio_norm)
            melspec = torch.squeeze(melspec, 0)
        else:
            melspec = torch.from_numpy(np.load(filename))
            assert melspec.size(0) == self.stft.n_mel_channels, (
                'Mel dimension mismatch: given {}, expected {}'.format(
                    melspec.size(0), self.stft.n_mel_channels))

        return melspec

    def get_ppg(self, PPG, speaker_embedding):
        # 传入的PPG是npy文件的路径
        # 还要考虑学长那边传过来的具体内容，做下路径处理
        # 路径处理TODO
        assert type(speaker_embedding) == "np.ndarray", "speaker_embedding的数据类型错误"
        # 读入的是列表套列表，一个npy文件，[[第一帧的72个音素概率], [第二帧的72个音素概率], ... ]
        PPG_temp = np.load(PPG)
        # 应该还要动model.py里的Tacotron2 Class. 原本TextMelLoader只是传出text的sequence, 之后是在Tacotron2 Class里每个embedding成512维
        for frame in PPG_temp:
            frame = np.append(frame, speaker_embedding)
        return PPG_temp

    def __getitem__(self, index):
        # 等于是按行读入
        return self.get_mel_PPG_id_pair(self.audiopaths_and_PPG[index])

    def __len__(self):
        return len(self.audiopaths_and_PPG)


class TextMelLoader(torch.utils.data.Dataset):
    """
        1) loads audio,text pairs
        2) normalizes text and converts them to sequences of one-hot vectors
        3) computes mel-spectrograms from audio files.
    """
    def __init__(self, audiopaths_and_text, hparams):
        self.audiopaths_and_text = load_filepaths_and_text(audiopaths_and_text)
        self.text_cleaners = hparams.text_cleaners
        self.max_wav_value = hparams.max_wav_value
        self.sampling_rate = hparams.sampling_rate
        self.load_mel_from_disk = hparams.load_mel_from_disk
        self.stft = layers.TacotronSTFT(
            hparams.filter_length, hparams.hop_length, hparams.win_length,
            hparams.n_mel_channels, hparams.sampling_rate, hparams.mel_fmin,
            hparams.mel_fmax)
        random.seed(hparams.seed)
        random.shuffle(self.audiopaths_and_text)

    def get_mel_text_pair(self, audiopath_and_text):
        # separate filename and text
        audiopath, text = audiopath_and_text[0], audiopath_and_text[1]
        text = self.get_text(text)
        mel = self.get_mel(audiopath)
        return (text, mel)

    def get_mel(self, filename):
        if not self.load_mel_from_disk:
            audio, sampling_rate = load_wav_to_torch(filename)
            if sampling_rate != self.stft.sampling_rate:
                raise ValueError("{} {} SR doesn't match target {} SR".format(
                    sampling_rate, self.stft.sampling_rate))
            audio_norm = audio / self.max_wav_value
            audio_norm = audio_norm.unsqueeze(0)
            audio_norm = torch.autograd.Variable(audio_norm, requires_grad=False)
            melspec = self.stft.mel_spectrogram(audio_norm)
            melspec = torch.squeeze(melspec, 0)
        else:
            melspec = torch.from_numpy(np.load(filename))
            assert melspec.size(0) == self.stft.n_mel_channels, (
                'Mel dimension mismatch: given {}, expected {}'.format(
                    melspec.size(0), self.stft.n_mel_channels))

        return melspec

    def get_text(self, text):
        text_norm = torch.IntTensor(text_to_sequence(text, self.text_cleaners))
        return text_norm

    def __getitem__(self, index):
        return self.get_mel_text_pair(self.audiopaths_and_text[index])

    def __len__(self):
        return len(self.audiopaths_and_text)


class TextMelCollate():
    """ Zero-pads model inputs and targets based on number of frames per setep
    """
    def __init__(self, n_frames_per_step):
        self.n_frames_per_step = n_frames_per_step

    def __call__(self, batch):
        """Collate's training batch from normalized text and mel-spectrogram
        PARAMS
        ------
        batch: [text_normalized, mel_normalized]
        """
        # Right zero-pad all one-hot text sequences to max input length
        input_lengths, ids_sorted_decreasing = torch.sort(
            torch.LongTensor([len(x[0]) for x in batch]),
            dim=0, descending=True)
        max_input_len = input_lengths[0]

        text_padded = torch.LongTensor(len(batch), max_input_len)
        text_padded.zero_()
        for i in range(len(ids_sorted_decreasing)):
            text = batch[ids_sorted_decreasing[i]][0]
            text_padded[i, :text.size(0)] = text

        # Right zero-pad mel-spec
        num_mels = batch[0][1].size(0)
        max_target_len = max([x[1].size(1) for x in batch])
        if max_target_len % self.n_frames_per_step != 0:
            max_target_len += self.n_frames_per_step - max_target_len % self.n_frames_per_step
            assert max_target_len % self.n_frames_per_step == 0

        # include mel padded and gate padded
        mel_padded = torch.FloatTensor(len(batch), num_mels, max_target_len)
        mel_padded.zero_()
        gate_padded = torch.FloatTensor(len(batch), max_target_len)
        gate_padded.zero_()
        output_lengths = torch.LongTensor(len(batch))
        for i in range(len(ids_sorted_decreasing)):
            mel = batch[ids_sorted_decreasing[i]][1]
            mel_padded[i, :, :mel.size(1)] = mel
            gate_padded[i, mel.size(1)-1:] = 1
            output_lengths[i] = mel.size(1)

        return text_padded, input_lengths, mel_padded, gate_padded, \
            output_lengths
