"""Per-process UI context: settings from .env (silent loader) and one shared Reader per data directory."""

import os
from pathlib import Path

import streamlit as st

from fireant_crawler.config import Settings, load_settings
from fireant_crawler.dotenv import read_env_file
from stock_ui.db import ReadResult, Reader
from stock_ui.tasks import ROOT


def settings() -> Settings:
    env_file = Path(os.environ.get("ENV_FILE", ROOT / ".env"))
    return load_settings({**read_env_file(env_file), **os.environ})


def data_dir() -> Path:
    d = settings().data_dir
    return d if d.is_absolute() else (ROOT / d)


@st.cache_resource
def _reader(path: str) -> Reader:
    return Reader(Path(path))


def reader() -> Reader:
    return _reader(str(data_dir()))


def freshness(result: ReadResult, what: str) -> bool:
    """Show why data is stale or missing. Returns True when there is something to display."""
    if result.stale and result.value is not None:
        st.warning(f"{what}: {result.note} - showing data as of {result.read_at:%H:%M:%S}")
    elif result.value is None:
        st.info(f"{what}: {result.note or 'no data'}")
    return result.value is not None
