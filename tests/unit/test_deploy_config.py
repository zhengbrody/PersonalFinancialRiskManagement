from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_aws_compose_passes_supabase_service_key_to_server_only_app_env():
    compose = (ROOT / "compose.aws.yml").read_text(encoding="utf-8")

    assert "SUPABASE_SERVICE_KEY=${SUPABASE_SERVICE_KEY:-}" in compose
    assert "server-only" in compose
    assert "must never be rendered in the UI" in compose


def test_deploy_script_forwards_supabase_service_key_from_secrets_to_env_file():
    deploy_script = (ROOT / "infra" / "scripts" / "deploy-phase-1.sh").read_text(encoding="utf-8")

    assert "SUPABASE_SERVICE_KEY" in deploy_script
    assert "trusted owner/admin cost dashboards" in deploy_script
