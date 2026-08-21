from src.tasks.moderation_tasks import recalculate_trust_scores

result = recalculate_trust_scores.delay()
print(f"task_id={result.id}")
print(f"task_result={result.get(timeout=30)}")
