import sys
from app.worker import poll_jira_for_remediation

def main():
    print(f"Manually triggering Jira Polling Task (Iterative Remediation Agent)...")
    result = poll_jira_for_remediation.delay()
    print(f"Task dispatched with ID: {result.id}")
    print("Check your Celery worker logs (or run `./demo logs`) to see the progression!")

if __name__ == "__main__":
    main()
