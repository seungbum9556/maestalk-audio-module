"""Maestalk's independently usable, offline instrument audio module."""
from .analysis import AudioAnalyzer, AnalysisConfig
from .result import AnalysisResult

__version__ = "0.4.1"
__all__ = ["AudioAnalyzer", "AnalysisConfig", "AnalysisResult"]
