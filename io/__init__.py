"""I/O layer: file readers and exporters for IR spectral data."""

# Re-export stdlib io symbols so that third-party libraries (e.g. ReportLab)
# that do ``from io import BytesIO`` still work when this project-local package
# shadows the stdlib ``io`` module during pytest runs.
import _io  # stdlib low-level io — always available, never shadowed

BytesIO = _io.BytesIO
StringIO = _io.StringIO
FileIO = _io.FileIO
BufferedReader = _io.BufferedReader
BufferedWriter = _io.BufferedWriter
BufferedRandom = _io.BufferedRandom
BufferedRWPair = _io.BufferedRWPair
TextIOWrapper = _io.TextIOWrapper
IncrementalNewlineDecoder = _io.IncrementalNewlineDecoder
DEFAULT_BUFFER_SIZE = _io.DEFAULT_BUFFER_SIZE
UnsupportedOperation = _io.UnsupportedOperation
open = _io.open  # noqa: A001
SEEK_SET = 0
SEEK_CUR = 1
SEEK_END = 2

# Public base classes exposed by the stdlib io module (backed by _io private names)
IOBase = _io._IOBase  # noqa: SLF001
RawIOBase = _io._RawIOBase  # noqa: SLF001
BufferedIOBase = _io._BufferedIOBase  # noqa: SLF001
TextIOBase = _io._TextIOBase  # noqa: SLF001
