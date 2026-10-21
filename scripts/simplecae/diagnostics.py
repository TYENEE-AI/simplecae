"""Stable recovery fields alongside original errors; no automatic retries."""
import errno
import subprocess


class WorkflowError(ValueError):
    def __init__(self, message, code, *, fields=(), next_action='inspect_evidence', details=None):
        super().__init__(message)
        self.diagnostic = {'code': code, 'retryable_unchanged': False,
                           'fields': list(fields), 'next_action': next_action,
                           'details': details or {}}


def diagnostic(exc):
    if hasattr(exc, 'diagnostic'): return exc.diagnostic
    from .schemas import ContractError
    if isinstance(exc, ContractError):
        return {'code': 'invalid_contract', 'retryable_unchanged': False,
                'next_action': 'repair_input_contract', 'details': exc.details}
    code, action = ('execution_error', 'inspect_retained_diagnostics')
    if isinstance(exc, subprocess.TimeoutExpired): code, action = 'native_timeout', 'review_budget_and_completed_stages'
    elif isinstance(exc, FileNotFoundError): code, action = 'missing_file', 'locate_required_input_or_runtime'
    elif isinstance(exc, OSError) and exc.errno == errno.ENOSPC: code, action = 'storage_exhausted', 'choose_output_volume_or_preview_archive'
    elif isinstance(exc, PermissionError): code, action = 'permission_denied', 'repair_execution_environment'
    elif isinstance(exc, (ValueError, TypeError)): code, action = 'invalid_input', 'inspect_input_and_evidence'
    return {'code': code, 'retryable_unchanged': False, 'fields': [], 'next_action': action,
            'details': {'exception_type': type(exc).__name__}}
