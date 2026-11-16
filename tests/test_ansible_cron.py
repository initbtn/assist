from pathlib import Path
import yaml

def test_ansible_playbook_syntax_and_structure():
    repo_root = Path(__file__).resolve().parent.parent
    playbook_path = repo_root / "ansible" / "playbook-cron.yml"
    assert playbook_path.is_file(), f"Playbook file not found at {playbook_path}"

    content = playbook_path.read_text(encoding="utf-8")
    data = yaml.safe_load(content)

    assert isinstance(data, list)
    assert len(data) >= 1
    play = data[0]

    assert play.get("hosts") == "edge_servers"
    tasks = play.get("tasks", [])
    assert len(tasks) >= 2

    # Check for cron task
    cron_tasks = [t for t in tasks if "ansible.builtin.cron" in t or "cron" in t]
    assert len(cron_tasks) >= 1
    cron_task = cron_tasks[0]
    cron_module = cron_task.get("ansible.builtin.cron") or cron_task.get("cron")

    assert cron_module.get("name") == "assist-daily-collect-and-brief"
    assert cron_module.get("minute") == "0"
    assert cron_module.get("hour") == "22"
    assert "daily-collect-and-brief.sh" in cron_module.get("job", "")

def test_ansible_hosts_and_script_exist():
    repo_root = Path(__file__).resolve().parent.parent
    hosts_path = repo_root / "ansible" / "hosts.ini"
    assert hosts_path.is_file()

    script_path = repo_root / "scripts" / "run-ansible-cron.sh"
    assert script_path.is_file()
