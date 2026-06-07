import logging
from celery import Celery

from app.agent import handle_incident
from app.config import get_settings

settings = get_settings()

celery_app = Celery("k8s_agent", broker=settings.celery_broker_url, backend=settings.celery_result_backend)
celery_app.conf.update(task_track_started=True)

# Schedule the polling task every 60 seconds
celery_app.conf.beat_schedule = {
    "poll-jira-every-60-seconds": {
        "task": "app.worker.poll_jira_for_remediation",
        "schedule": 60.0,
    },
}

logger = logging.getLogger(__name__)


@celery_app.task(name="app.worker.process_incident")
def process_incident(payload: dict) -> dict:
    from redis import Redis
    s = get_settings()
    redis_client = Redis.from_url(s.redis_url, decode_responses=True)
    return handle_incident(payload, s, redis_client)


@celery_app.task(name="app.worker.poll_jira_for_remediation")
def poll_jira_for_remediation() -> dict:
    from app.clients.jira import JiraClient
    from app.graphs.remediation import run_remediation
    from app.schemas import JiraIssue

    s = get_settings()
    jira = JiraClient(s)

    logger.info("Polling Jira for issues requiring remediation...")
    
    jql = f'project = "{s.jira_project_key}" AND status = "To Do" AND labels = "AI-Remediation"'
    issues = jira.search_issues(jql)
    
    processed_count = 0
    failed_count = 0
    for issue_data in issues:
        issue_key = issue_data["key"]
        issue = JiraIssue(key=issue_key, url=f"{s.jira_base_url}/browse/{issue_key}")
        
        logger.info("Picking up issue %s for iterative remediation", issue_key)
        result = run_remediation(issue.key, issue.url, s, jira=jira)
        if result["status"] == "success":
            processed_count += 1
        else:
            failed_count += 1
        
    return {"status": "success", "processed": processed_count, "failed": failed_count}
