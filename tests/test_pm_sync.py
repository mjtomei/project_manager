"""Tests for hash-based PR ID generation."""

from pm_core import store


class TestGeneratePrId:
    """Tests for hash-based PR ID generation."""

    def test_deterministic(self):
        """Same title+desc always produces the same ID."""
        id1 = store.generate_pr_id("Add feature X", "Description")
        id2 = store.generate_pr_id("Add feature X", "Description")
        assert id1 == id2

    def test_starts_with_pr_prefix(self):
        """Generated IDs start with 'pr-'."""
        pr_id = store.generate_pr_id("Test PR", "")
        assert pr_id.startswith("pr-")

    def test_hash_length(self):
        """Default hash is 7 hex chars."""
        pr_id = store.generate_pr_id("Test PR", "")
        # pr- prefix + 7 hex chars
        assert len(pr_id) == 3 + 7

    def test_different_titles_different_ids(self):
        """Different titles produce different IDs."""
        id1 = store.generate_pr_id("Feature A", "")
        id2 = store.generate_pr_id("Feature B", "")
        assert id1 != id2

    def test_different_descriptions_different_ids(self):
        """Different descriptions produce different IDs."""
        id1 = store.generate_pr_id("Same Title", "Desc A")
        id2 = store.generate_pr_id("Same Title", "Desc B")
        assert id1 != id2

    def test_avoids_existing_ids(self):
        """Extends hash when collision with existing ID."""
        pr_id = store.generate_pr_id("Test", "")
        # Force collision by including the generated ID in existing set
        extended = store.generate_pr_id("Test", "", existing_ids={pr_id})
        assert extended != pr_id
        assert extended.startswith("pr-")
        # Extended hash should be longer
        assert len(extended) > len(pr_id)

    def test_empty_description_ok(self):
        """Works with empty description."""
        pr_id = store.generate_pr_id("Title Only", "")
        assert pr_id.startswith("pr-")

    def test_no_existing_ids(self):
        """Works when no existing IDs provided."""
        pr_id = store.generate_pr_id("Title", "Desc", existing_ids=None)
        assert pr_id.startswith("pr-")

    def test_backwards_compatible_with_old_ids(self):
        """Old pr-001 style IDs in existing set don't interfere."""
        existing = {"pr-001", "pr-002", "pr-003"}
        pr_id = store.generate_pr_id("New Feature", "", existing_ids=existing)
        assert pr_id.startswith("pr-")
        assert pr_id not in existing
