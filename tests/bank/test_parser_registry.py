"""Cross-bank integration tests for parser registry."""
import os

import pytest

from services.bank.parsers.registry import BANK_PARSERS, BankParserNotReady, list_parsers, parse_statement

SAMPLES_ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "samples", "bank_statements")

EXPECTED_PARSERS = {"BBVA", "SANTANDER", "CITIBANAMEX", "SCOTIABANK", "BANBAJIO", "BANREGIO", "AZTECA"}


class TestRegistry:
    def test_all_parsers_registered(self):
        registered = set(BANK_PARSERS.keys())
        assert EXPECTED_PARSERS.issubset(registered), f"Missing: {EXPECTED_PARSERS - registered}"

    def test_all_parsers_experimental(self):
        for name in EXPECTED_PARSERS:
            _, is_exp = BANK_PARSERS[name]
            assert is_exp, f"{name} should be EXPERIMENTAL"

    def test_list_parsers(self):
        info = list_parsers()
        for name in EXPECTED_PARSERS:
            assert name in info
            assert "experimental" in info[name]
            assert "parser" in info[name]

    def test_unknown_bank_raises(self):
        with pytest.raises(KeyError):
            parse_statement("NONEXISTENT_BANK", "/fake/path.pdf")

    def test_experimental_blocked_in_prod(self, monkeypatch):
        monkeypatch.setenv("ENV", "prod")
        monkeypatch.setenv("DEV_MODE", "0")
        with pytest.raises(BankParserNotReady):
            parse_statement("BBVA", "/fake/path.pdf")

    def test_experimental_allowed_in_dev(self, monkeypatch):
        monkeypatch.setenv("ENV", "dev")
        monkeypatch.setenv("DEV_MODE", "1")
        # Should not raise BankParserNotReady — parser runs (returns empty for missing file)
        result = parse_statement("BBVA", "/fake/nonexistent.pdf")
        assert isinstance(result, list)


def _have_any_samples():
    return os.path.isdir(SAMPLES_ROOT) and any(
        os.path.isdir(os.path.join(SAMPLES_ROOT, d)) for d in os.listdir(SAMPLES_ROOT)
    )


@pytest.mark.skipif(not _have_any_samples(), reason="No bank statement samples")
class TestCrossBankDispatch:
    """Test parse_statement dispatch to correct parser via registry."""

    def _find_sample(self, bank_dir: str) -> str | None:
        d = os.path.join(SAMPLES_ROOT, bank_dir)
        if not os.path.isdir(d):
            return None
        pdfs = [f for f in os.listdir(d) if f.endswith(".pdf")]
        return os.path.join(d, pdfs[0]) if pdfs else None

    def test_dispatch_bbva(self):
        path = self._find_sample("bbva")
        if not path:
            pytest.skip("No BBVA samples")
        movs = parse_statement("BBVA", path)
        assert isinstance(movs, list)
        assert len(movs) > 0

    def test_dispatch_santander(self):
        path = self._find_sample("santander")
        if not path:
            pytest.skip("No Santander samples")
        movs = parse_statement("SANTANDER", path)
        assert isinstance(movs, list)
        assert len(movs) > 0

    def test_dispatch_citibanamex(self):
        path = self._find_sample("citibanamex")
        if not path:
            pytest.skip("No Citibanamex samples")
        movs = parse_statement("CITIBANAMEX", path)
        assert isinstance(movs, list)
        assert len(movs) > 0

    def test_dispatch_scotiabank(self):
        path = self._find_sample("scotiabank")
        if not path:
            pytest.skip("No Scotiabank samples")
        movs = parse_statement("SCOTIABANK", path)
        assert isinstance(movs, list)
        assert len(movs) > 0

    def test_dispatch_azteca(self):
        path = self._find_sample("azteca")
        if not path:
            pytest.skip("No Azteca samples")
        movs = parse_statement("AZTECA", path)
        assert isinstance(movs, list)
        assert len(movs) > 0

    def test_all_parsers_return_standard_keys(self):
        """Every parser must return dicts with the standard movement keys."""
        required_keys = {"fecha", "descripcion", "deposito", "retiro", "saldo", "referencia"}
        bank_dirs = {"bbva": "BBVA", "santander": "SANTANDER", "citibanamex": "CITIBANAMEX",
                     "scotiabank": "SCOTIABANK", "azteca": "AZTECA", "banbajio": "BANBAJIO",
                     "banregio": "BANREGIO"}
        tested = 0
        for dir_name, bank_name in bank_dirs.items():
            path = self._find_sample(dir_name)
            if not path:
                continue
            movs = parse_statement(bank_name, path)
            for m in movs:
                assert required_keys.issubset(m.keys()), f"{bank_name}: missing keys {required_keys - m.keys()}"
            tested += 1
        assert tested > 0, "No samples found for any bank"
