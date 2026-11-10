"""Evaluation harness for PII detection in request free text (Issue #585).

Compares detection approaches for ``requests.req_subj`` and ``requests.req_desc``
on a synthetic labelled dataset. Detection modules use only the Python standard
library; ``boto3`` is imported lazily and only for the optional live Amazon
Comprehend run.
"""
