"""WFD Coding Assistant.

Numerical libraries (OpenBLAS / OpenMP / MKL, used by numpy and scikit-learn for the evidence index) start one worker
thread per CPU of the whole host machine by default. On a hosting plan with a fraction of one CPU (Render 0.5 CPU) that
many busy threads can exhaust the CPU allowance and get the whole process paused, so the web server stops answering
its health check (incident 2026-10-01, DECISIONS D-033). Limit them to one thread unless explicitly overridden.
This must run before numpy is imported, which is why it lives in the package __init__.
"""
import os as _os

for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    _os.environ.setdefault(_v, _os.environ.get("WFD_NATIVE_THREADS", "1"))
