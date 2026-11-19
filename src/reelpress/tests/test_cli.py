from reelpress.cli import main


def test_cli_jobs_and_config(settings):
    assert main(["jobs"]) == 0
    assert main(["config"]) == 0
    assert main(["doctor"]) == 0


def test_cli_generate_requires_input(settings):
    assert main(["generate"]) == 1
