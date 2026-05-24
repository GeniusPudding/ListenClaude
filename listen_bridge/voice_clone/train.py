"""GPT-SoVITS s1 (GPT) fine-tuning driver, generalised for any voice.

Replaces the original ``voices/ig-demo/train-gptsovits.py`` one-off
script. Reads paths from a voice profile, runs the four-stage GPT-SoVITS
training inside .venv-gptsovits, and writes the resulting GPT
checkpoint location back into profile.json so gptsovits.py can find it.

We deliberately skip s2 (SoVITS) fine-tuning: on small datasets (~50
segments) it overfits and produces garbled audio. The base v2 SoVITS
plus a reference clip gives cleaner voice cloning anchored to the
fine-tuned GPT's prosody.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

from . import profile as profile_mod
from .. import config


_GSV_DIR = config.GPTSOVITS_SOURCE_DIR
_GSV_PY = config.GPTSOVITS_PYTHON
_PRETRAINED = os.path.join(_GSV_DIR, "GPT_SoVITS", "pretrained_models")

# Shared base v2 weights produced by the GPT-SoVITS install script.
_BERT_BASE     = os.path.join(_PRETRAINED, "chinese-roberta-wwm-ext-large")
_HUBERT_BASE   = os.path.join(_PRETRAINED, "chinese-hubert-base")
_S2G_BASE      = os.path.join(_PRETRAINED, "gsv-v2final-pretrained", "s2G2333k.pth")
_S1_BASE       = os.path.join(_PRETRAINED, "gsv-v2final-pretrained",
                              "s1bert25hz-5kh-longer-epoch=12-step=369668.ckpt")
_S2_CFG_BASE   = os.path.join(_GSV_DIR, "GPT_SoVITS", "configs", "s2.json")
_S1_CFG_BASE   = os.path.join(_GSV_DIR, "GPT_SoVITS", "configs", "s1longer-v2.yaml")


def _run(cmd: list[str], env: dict[str, str]) -> None:
    """Invoke a GPT-SoVITS-internal script inside .venv-gptsovits with
    PYTHONPATH set so its bare-package imports (`from text.cleaner ...`,
    `from tools.my_utils ...`) resolve correctly."""
    full_env = {**os.environ, **env}
    full_env["PYTHONIOENCODING"] = "utf-8"
    full_env["PYTHONUTF8"] = "1"
    extra = f"{os.path.join(_GSV_DIR, 'GPT_SoVITS')}{os.pathsep}{_GSV_DIR}"
    full_env["PYTHONPATH"] = (
        extra + os.pathsep + full_env.get("PYTHONPATH", "")
    ).rstrip(os.pathsep)
    print(f"  $ {' '.join(cmd)}")
    r = subprocess.run(cmd, env=full_env, cwd=_GSV_DIR)
    if r.returncode != 0:
        raise RuntimeError(f"step failed (exit {r.returncode})")


def _merge_preprocess_parts(opt_dir: str) -> None:
    """GPT-SoVITS writes 1a/1c outputs as ``*-0.{txt,tsv}`` part files
    that the train step expects pre-merged into ``2-name2text.txt`` /
    ``6-name2semantic.tsv``. webui.py does this implicitly via
    ``open1abc``; we replicate it for headless use."""
    txt_parts = sorted(
        os.path.join(opt_dir, f) for f in os.listdir(opt_dir)
        if f.startswith("2-name2text-") and f.endswith(".txt")
    )
    if txt_parts:
        with open(os.path.join(opt_dir, "2-name2text.txt"), "w", encoding="utf-8") as out:
            for p in txt_parts:
                with open(p, encoding="utf-8") as f:
                    out.write(f.read())

    tsv_parts = sorted(
        os.path.join(opt_dir, f) for f in os.listdir(opt_dir)
        if f.startswith("6-name2semantic-") and f.endswith(".tsv")
    )
    if tsv_parts:
        with open(os.path.join(opt_dir, "6-name2semantic.tsv"), "w", encoding="utf-8") as out:
            out.write("item_name\tsemantic_audio\n")
            for p in tsv_parts:
                with open(p, encoding="utf-8") as f:
                    content = f.read().strip("\n")
                    if content:
                        out.write(content + "\n")


def run(name: str, *, epochs: int = 15, batch_size: int = 4) -> str:
    """Run the full GPT-SoVITS s1 fine-tune pipeline (1a → 1b → 1c → s1)
    for voice <name>. Returns the absolute path of the final half-weights
    GPT checkpoint, and updates profile.json's ``engines.gptsovits``
    section to reference it."""
    prof = profile_mod.load(name)
    list_file = os.path.join(prof.home, "list.txt")
    if not os.path.isfile(list_file):
        raise FileNotFoundError(f"no list.txt under {prof.home} — run slice first")

    exp_root = os.path.join(prof.home, "training")
    opt_dir = os.path.join(exp_root, name)
    (os.path.join(exp_root, "GPT_weights")).replace("\\", "/")
    os.makedirs(opt_dir, exist_ok=True)
    os.makedirs(os.path.join(exp_root, "GPT_weights"), exist_ok=True)
    os.makedirs(os.path.join(opt_dir, "logs_s2_v2"), exist_ok=True)

    if not os.path.isfile(_S1_BASE):
        raise FileNotFoundError(
            "GPT-SoVITS base weights missing — re-run the install script "
            f"to fetch gsv-v2final-pretrained into {_PRETRAINED}"
        )

    common = {
        "inp_text":             list_file,
        "inp_wav_dir":          "",
        "exp_name":             name,
        "i_part":               "0",
        "all_parts":            "1",
        "_CUDA_VISIBLE_DEVICES": "0",
        "opt_dir":              opt_dir,
        "is_half":              "True",
        "version":              "v2",
    }

    # 1a: phonemes + Chinese BERT features
    print(f"\n[train] {name} — stage 1a: text + BERT")
    _run(
        [_GSV_PY, "-s", "GPT_SoVITS/prepare_datasets/1-get-text.py"],
        env={**common, "bert_pretrained_dir": _BERT_BASE},
    )

    # 1b: HuBERT features + 32k waveform
    print(f"\n[train] {name} — stage 1b: HuBERT")
    _run(
        [_GSV_PY, "-s", "GPT_SoVITS/prepare_datasets/2-get-hubert-wav32k.py"],
        env={**common, "cnhubert_base_dir": _HUBERT_BASE},
    )

    # 1c: semantic tokens (HuBERT → VQ codes via base SoVITS encoder)
    print(f"\n[train] {name} — stage 1c: semantic tokens")
    _run(
        [_GSV_PY, "-s", "GPT_SoVITS/prepare_datasets/3-get-semantic.py"],
        env={**common, "pretrained_s2G": _S2G_BASE, "s2config_path": _S2_CFG_BASE},
    )

    _merge_preprocess_parts(opt_dir)

    # s1: GPT (text → semantic) fine-tune
    print(f"\n[train] {name} — stage s1: GPT fine-tune ({epochs} epochs)")
    import yaml  # pyyaml is part of the GPT-SoVITS deps
    with open(_S1_CFG_BASE, encoding="utf-8") as f:
        s1_cfg = yaml.safe_load(f)
    s1_cfg["train"].update({
        "batch_size": batch_size,
        "epochs": epochs,
        "exp_name": name,
        "save_every_n_epoch": max(1, epochs // 3),
        "if_save_latest": True,
        "if_save_every_weights": True,
        "half_weights_save_dir": os.path.join(exp_root, "GPT_weights"),
        "precision": "32-true",  # Windows + Lightning fp16 hits ACCESS_VIOLATION
    })
    s1_cfg["data"]["num_workers"] = 0
    s1_cfg["pretrained_s1"] = _S1_BASE
    s1_cfg["train_semantic_path"] = os.path.join(opt_dir, "6-name2semantic.tsv")
    s1_cfg["train_phoneme_path"]  = os.path.join(opt_dir, "2-name2text.txt")
    s1_cfg["output_dir"]          = os.path.join(opt_dir, "logs_s1")

    patched_cfg = os.path.join(exp_root, "s1.yaml")
    with open(patched_cfg, "w", encoding="utf-8") as f:
        yaml.safe_dump(s1_cfg, f, allow_unicode=True)

    _run(
        [_GSV_PY, "-s", "GPT_SoVITS/s1_train.py", "--config_file", patched_cfg],
        env={"_CUDA_VISIBLE_DEVICES": "0", "is_half": "True"},
    )

    # Locate the latest half-weight checkpoint and pin its path in
    # profile.json so gptsovits.py knows what to load.
    gpt_weights_dir = os.path.join(exp_root, "GPT_weights")
    ckpts = [f for f in os.listdir(gpt_weights_dir) if f.endswith(".ckpt")]
    if not ckpts:
        raise RuntimeError(f"no GPT ckpt under {gpt_weights_dir}")
    # Highest epoch number wins.
    def _ep(fn: str) -> int:
        import re
        m = re.search(r"-e(\d+)\.ckpt$", fn)
        return int(m.group(1)) if m else -1
    latest = max(ckpts, key=_ep)
    ckpt_abs = os.path.join(gpt_weights_dir, latest)

    prof.update_engine("gptsovits", {
        "gpt_ckpt": os.path.relpath(ckpt_abs, prof.home),
        "epochs_trained": _ep(latest),
    })
    prof.save()
    print(f"\n[train] done. checkpoint: {ckpt_abs}")
    return ckpt_abs
