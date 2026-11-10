"""Close only the two reviewed incidents after activating their fixes."""

import httpx


def main():
    incidents = {
        "948a5c3d84e44e6eb54f69d63d9751e2": "infrastructure_failure",
        "8f80284e2e694345963a2e6deada6acc": "execution_failed:474ccebb3e214c5497238cf9eb82e53e",
    }
    with httpx.Client(
        transport=httpx.HTTPTransport(uds="/var/lib/supervisor-agent/daemon.sock"),
        base_url="http://supervisor",
        timeout=30,
    ) as client:
        state = client.get("/v1/status")
        state.raise_for_status()
        if state.json()["enabled"] or state.json()["active_execution"]:
            raise RuntimeError("Dispatch must remain stopped during maintenance")
        for item, fingerprint in incidents.items():
            response = client.get("/v1/inbox/" + item)
            response.raise_for_status()
            alert = response.json()
            if alert["fingerprint"] != fingerprint or alert["origin"] != "system":
                raise RuntimeError("Incident does not match the reviewed alert")
            if alert["state"] == "resolved":
                continue
            response = client.post(
                "/v1/action",
                json={
                    "operation": "alert_resolve",
                    "id": item,
                    "resolution": "Reviewed incident fixed and activated: startup readiness and safe non-thinking "
                    "compaction are implemented and tested. Evidence is in the November run review and recovery "
                    "notes. Work remains intentionally stopped pending the next research decision.",
                },
            )
            response.raise_for_status()
        print("Reviewed incidents resolved; dispatch remains disabled.")


if __name__ == "__main__":
    main()
