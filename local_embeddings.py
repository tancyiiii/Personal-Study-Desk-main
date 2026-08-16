"""Local Chinese embedding model for offline, provider-independent RAG."""

from __future__ import annotations

import os
import sys
import threading
from typing import List, Optional

import numpy as np
import requests
from langchain_core.embeddings import Embeddings

from resource_path import resource_path


MODEL_REPO = "Xenova/bge-small-zh-v1.5"
MODEL_FILES = (
    "config.json",
    "tokenizer.json",
    "special_tokens_map.json",
    "tokenizer_config.json",
    "vocab.txt",
    "onnx/model.onnx",
)
QUERY_INSTRUCTION = "为这个句子生成表示以用于检索相关文章："
MAX_SEQUENCE_LENGTH = 512


def _user_model_dir() -> str:
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, "StudyAssistant", "models", "bge-small-zh-v1.5")


def _download_model(target_dir: str) -> None:
    """Download the ONNX Chinese embedding model from a domestic HF mirror."""
    mirror = os.environ.get("HF_ENDPOINT", "https://hf-mirror.com")
    os.makedirs(target_dir, exist_ok=True)
    for relative_path in MODEL_FILES:
        target = os.path.join(target_dir, relative_path)
        if os.path.isfile(target):
            continue
        os.makedirs(os.path.dirname(target), exist_ok=True)
        url = f"{mirror.rstrip('/')}/{MODEL_REPO}/resolve/main/{relative_path}"
        response = requests.get(url, stream=True, timeout=90)
        response.raise_for_status()
        temp_path = target + ".part"
        with open(temp_path, "wb") as handle:
            for chunk in response.iter_content(1024 * 1024):
                if chunk:
                    handle.write(chunk)
        os.replace(temp_path, target)


class LocalChineseEmbeddings(Embeddings):
    """Embed Chinese text with BGE-small-zh-v1.5 using ONNX Runtime."""

    def __init__(self, model_dir: Optional[str] = None):
        self.model_dir = self._resolve_model_dir(model_dir)
        self._tokenizer = None
        self._session = None
        self._lock = threading.Lock()

    @staticmethod
    def _resolve_model_dir(model_dir: Optional[str]) -> str:
        candidates = [
            model_dir,
            resource_path(os.path.join("assets", "models", "bge-small-zh-v1.5")),
            _user_model_dir(),
        ]
        for candidate in candidates:
            if not candidate:
                continue
            if os.path.isfile(os.path.join(candidate, "tokenizer.json")) and os.path.isfile(
                os.path.join(candidate, "onnx", "model.onnx")
            ):
                return candidate

        user_dir = _user_model_dir()
        try:
            _download_model(user_dir)
        except Exception as exc:
            raise RuntimeError(
                "无法加载本地中文向量模型，且下载失败。"
                f"请检查网络或模型目录：{exc}"
            ) from exc
        return user_dir

    def _ensure_loaded(self):
        if self._tokenizer is not None:
            return
        from onnxruntime import InferenceSession
        from tokenizers import Tokenizer

        tokenizer_path = os.path.join(self.model_dir, "tokenizer.json")
        model_path = os.path.join(self.model_dir, "onnx", "model.onnx")
        if not os.path.isfile(tokenizer_path) or not os.path.isfile(model_path):
            raise RuntimeError(
                f"本地中文向量模型不完整：{self.model_dir}"
            )
        self._tokenizer = Tokenizer.from_file(tokenizer_path)
        self._tokenizer.enable_truncation(max_length=MAX_SEQUENCE_LENGTH)
        self._session = InferenceSession(
            model_path,
            providers=["CPUExecutionProvider"],
        )

    def _embed_batch(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        self._ensure_loaded()
        with self._lock:
            encodings = self._tokenizer.encode_batch(texts)
            batch_size = len(encodings)
            sequence_length = max(
                (min(len(item.ids), MAX_SEQUENCE_LENGTH) for item in encodings),
                default=1,
            )
            input_ids = np.zeros((batch_size, sequence_length), dtype=np.int64)
            attention_mask = np.zeros(
                (batch_size, sequence_length), dtype=np.int64
            )
            token_type_ids = np.zeros(
                (batch_size, sequence_length), dtype=np.int64
            )
            for row, encoding in enumerate(encodings):
                length = min(len(encoding.ids), sequence_length)
                input_ids[row, :length] = encoding.ids[:length]
                attention_mask[row, :length] = encoding.attention_mask[:length]
                type_ids = getattr(encoding, "type_ids", None)
                if type_ids:
                    token_type_ids[row, :length] = type_ids[:length]

            outputs = self._session.run(
                None,
                {
                    "input_ids": input_ids,
                    "attention_mask": attention_mask,
                    "token_type_ids": token_type_ids,
                },
            )
            hidden_states = np.asarray(outputs[0], dtype=np.float32)
            mask = attention_mask[:, :, np.newaxis].astype(np.float32)
            summed = np.sum(hidden_states * mask, axis=1)
            count = np.maximum(np.sum(mask, axis=1), 1e-9)
            vectors = summed / count
            norms = np.linalg.norm(vectors, axis=1, keepdims=True)
            vectors = vectors / np.maximum(norms, 1e-12)
            return vectors.astype(np.float32).tolist()

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return self._embed_batch([text.strip() for text in texts])

    def embed_query(self, text: str) -> List[float]:
        query_text = f"{QUERY_INSTRUCTION}{text.strip()}"
        return self._embed_batch([query_text])[0]
