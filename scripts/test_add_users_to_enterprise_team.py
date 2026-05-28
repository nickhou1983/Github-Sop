import importlib.util
from pathlib import Path


SCRIPT_PATH = Path(__file__).with_name("add-users-to-enterprise-team.py")


def load_script_module():
    spec = importlib.util.spec_from_file_location("add_users_to_enterprise_team", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_read_users_from_csv_ignores_header_blank_rows_and_deduplicates(tmp_path):
    module = load_script_module()
    users_file = tmp_path / "users.csv"
    users_file.write_text(
        "username\n"
        " alice_enterprise \n"
        "\n"
        "bob_enterprise\n"
        "alice_enterprise\n",
        encoding="utf-8",
    )

    assert module.read_users_from_csv(users_file) == [
        "alice_enterprise",
        "bob_enterprise",
    ]


def test_build_membership_url_uses_enterprise_team_endpoint():
    module = load_script_module()

    assert module.build_membership_url(
        "contoso", "engineering", "alice_enterprise"
    ) == (
        "https://api.github.com/enterprises/contoso/teams/"
        "engineering/memberships/alice_enterprise"
    )


def test_process_users_dry_run_does_not_call_api():
    module = load_script_module()

    def fail_if_called(*args, **kwargs):
        raise AssertionError("API should not be called during dry-run")

    summary = module.process_users(
        enterprise="contoso",
        team_slug="engineering",
        users=["alice_enterprise", "bob_enterprise"],
        role="member",
        token="unused",
        dry_run=True,
        add_membership=fail_if_called,
    )

    assert summary.success_count == 0
    assert summary.fail_count == 0
    assert summary.skipped_count == 2
    assert summary.total_count == 2