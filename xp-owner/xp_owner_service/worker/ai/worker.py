import logging

from xp_owner_service.app.services.ai.result import publish
from xp_owner_service.app.services.chat.turn import candidates, claim_next, published_reply
from xp_owner_service.worker.ai.gateway import execute, read_run

logger = logging.getLogger(__name__)


def publish_request(factory, claim_id, request_id):
    return publish(factory, claim_id, read_run(request_id))


def run_once(factory, worker_id="owner-worker"):
    results = []
    for conversation_id in candidates(factory):
        claim = claim_next(factory, conversation_id, worker_id)
        if not claim.get("claimed"):
            results.append(claim)
            continue
        run = execute(claim)
        if run is None:
            results.append({"pending": True, "turn_id": claim["turn_id"]})
            continue
        try:
            results.append(publish(factory, claim["claim_id"], run))
        except Exception:
            # Never write a compensating failure after an unknown COMMIT result.
            results.append(published_reply(factory, claim["turn_id"]))
    return results


def loop(factory, stop):
    while not stop.is_set():
        try:
            run_once(factory)
        except Exception:
            logger.error("Owner worker iteration failed; will retry after lease")
        stop.wait(0.25)
