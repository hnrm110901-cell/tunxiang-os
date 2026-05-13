"""[T2] Issue #501 Phase 2 — _CollisionEnforcer behavior tests.

Tests enforcement layer added in PR for Issue #501 Phase 2:
  - bare-NS `from services.X import ...` where X ∈ COLLISION_BASENAMES → ImportError
  - FQN `from services.<svc>.src.services.X import ...` bypasses enforcer
  - Files in _NOQA_ALLOWED_FILES bypass enforcer
  - Non-collision bare-NS imports unaffected (pass through to namespace resolution)

Tier 2 — test-infra import semantics. No DB / no Tier 1 path touched.
"""

import importlib
import sys

import pytest

import conftest as repo_conftest


class TestCollisionEnforcerInstalled:
    def test_enforcer_in_sys_meta_path(self) -> None:
        assert any(
            isinstance(f, repo_conftest._CollisionEnforcer)
            for f in sys.meta_path
        ), "Enforcer must be installed in sys.meta_path"

    def test_collision_basenames_nonempty(self) -> None:
        # Sanity: hardcoded set must list real collision groups
        assert len(repo_conftest.COLLISION_BASENAMES) >= 12

    def test_noqa_allowed_files_includes_known_exceptions(self) -> None:
        # PR #494 / #497 留 noqa 例外必须保留 allowlist
        assert "test_approval_engine.py" in repo_conftest._NOQA_ALLOWED_FILES
        assert "test_auto_procurement.py" in repo_conftest._NOQA_ALLOWED_FILES


class TestEnforcerBlocksCollisionBareNS:
    """Core Phase 2 enforcement — collision bare-NS imports must raise."""

    @pytest.mark.parametrize(
        "collision_name",
        ["repository", "approval_engine", "invoice_service", "report_engine"],
    )
    def test_bare_ns_collision_raises_importerror(self, collision_name: str) -> None:
        # Each collision basename → bare-NS import must raise with FQN guidance.
        # Use importlib (not `from ... import ...`) to programmatically trigger
        # without triggering test-file's own collision allowlist bypass.
        with pytest.raises(ImportError, match=r"bare-NS .* blocked"):
            importlib.import_module(f"services.{collision_name}")

    def test_blocked_error_message_mentions_fqn_guidance(self) -> None:
        with pytest.raises(ImportError) as exc_info:
            importlib.import_module("services.repository")
        assert "FQN" in str(exc_info.value)
        assert "<svc>.src.services.repository" in str(exc_info.value)


class TestEnforcerAllowsNonCollision:
    """Non-collision modules pass through enforcer (no false positive)."""

    def test_non_collision_module_not_blocked_by_enforcer(self) -> None:
        # services.banquet_payment_service exists only in tx-trade — not a
        # collision basename. Enforcer must not block. Actual import may still
        # fail (depends on test env state), but the error must NOT be the
        # enforcer's `bare-NS ... blocked` message.
        try:
            importlib.import_module("services.banquet_payment_service")
        except ImportError as e:
            assert "bare-NS" not in str(e) or "blocked" not in str(e), (
                f"Enforcer should not block non-collision module, got: {e}"
            )


class TestAllowlistBypass:
    """Allowlist bypass via _NOQA_ALLOWED_FILES — M2 coverage from §19 review.

    When a caller frame's file basename is in _NOQA_ALLOWED_FILES, the enforcer
    must return None (bypass) instead of raising. This preserves pre-existing
    noqa-marked bare-NS imports (test_approval_engine.py / test_auto_procurement.py).

    Direct unit test of find_spec with mocked frame — verifies the frame walk
    logic, independent of how/when the enforcer is triggered.
    """

    def test_noqa_allowed_file_bypasses_enforcer(self) -> None:
        from unittest import mock

        enforcer = repo_conftest._CollisionEnforcer()
        fake_frame = mock.MagicMock()
        fake_frame.f_code.co_filename = "/some/path/to/test_approval_engine.py"
        fake_frame.f_back = None

        with mock.patch("sys._getframe", return_value=fake_frame):
            result = enforcer.find_spec("services.approval_engine")

        assert result is None, "Allowlisted file must bypass enforcer (return None)"

    def test_non_allowed_file_still_blocked(self) -> None:
        from unittest import mock

        enforcer = repo_conftest._CollisionEnforcer()
        fake_frame = mock.MagicMock()
        fake_frame.f_code.co_filename = "/some/path/to/test_random_other.py"
        fake_frame.f_back = None

        with mock.patch("sys._getframe", return_value=fake_frame):
            with pytest.raises(ImportError, match=r"bare-NS .* blocked"):
                enforcer.find_spec("services.approval_engine")

    def test_allowlist_bypass_works_at_deeper_frame(self) -> None:
        # Caller stack may have intermediate frames (e.g., import wrappers);
        # allowlist match anywhere in the walk should bypass.
        from unittest import mock

        enforcer = repo_conftest._CollisionEnforcer()
        intermediate = mock.MagicMock()
        intermediate.f_code.co_filename = "/some/random/intermediate.py"
        allowed = mock.MagicMock()
        allowed.f_code.co_filename = "/svc/tests/test_auto_procurement.py"
        allowed.f_back = None
        intermediate.f_back = allowed

        with mock.patch("sys._getframe", return_value=intermediate):
            result = enforcer.find_spec("services.approval_engine")

        assert result is None, (
            "Allowlist file at deeper frame should still bypass enforcer"
        )


class TestFQNBypassesEnforcer:
    """FQN (5+ segments) bypasses enforcer — only `services.X` (2-seg) intercepted."""

    def test_fqn_form_not_blocked(self) -> None:
        # FQN `services.tx_analytics.src.services.repository` — enforcer must
        # not intercept. This is the form B1 sweep migrated bare-NS hits to.
        try:
            importlib.import_module(
                "services.tx_analytics.src.services.repository"
            )
        except ImportError as e:
            assert "bare-NS" not in str(e) or "blocked" not in str(e), (
                f"FQN must not be blocked by enforcer, got: {e}"
            )

    def test_three_segment_services_form_not_blocked(self) -> None:
        # Edge case: `services.tx_analytics.foo` (3-seg) — enforcer only
        # intercepts exactly 2-seg, so this passes through.
        try:
            importlib.import_module("services.tx_analytics.nonexistent")
        except ImportError as e:
            assert "bare-NS" not in str(e) or "blocked" not in str(e)
