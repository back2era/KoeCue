from ai_japanese_interview_assistant.benchmark_wav import latency_summary


def test_latency_report_does_not_hide_missing_observations():
    samples = [n / 100 for n in range(1, 30)] + [None]
    summary = latency_summary(samples, 2.5)
    assert summary["expected"] == 30
    assert summary["measured"] == 29
    assert summary["p95_s"] == 0.28
    assert summary["passed"] is False


def test_latency_report_uses_nearest_rank_and_checks_the_target():
    summary = latency_summary([n / 10 for n in range(1, 31)], 2.5)
    assert summary["p50_s"] == 1.5
    assert summary["p95_s"] == 2.9
    assert summary["passed"] is False
