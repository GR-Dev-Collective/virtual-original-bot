from app.config import Settings


def test_asr_defaults_run_without_host_cuda_libraries() -> None:
    settings = Settings(_env_file=None)

    assert settings.asr_device == "cpu"
    assert settings.asr_compute_type == "int8"
