import logging

import boto3
import json
import os

CLUSTER = os.environ["CLUSTER"]
TASK_DEFINITION = os.environ["TASK_DEFINITION"]

logger = logging.getLogger(__name__)


def lambda_handler(event, context):
    logger.info("Starting ecs run task lambda...")
    ecs = boto3.client("ecs")
    response = ecs.run_task(
        cluster=CLUSTER,
        taskDefinition=TASK_DEFINITION,
        launchType="FARGATE",
        count=1,
        platformVersion="LATEST",
        networkConfiguration={
            "awsvpcConfiguration": {
                "subnets": ["subnet-f0d61796", "subnet-085aac40"],
                "assignPublicIp": "ENABLED",
            }
        },
        overrides={
            "containerOverrides": [
                {
                    "name": "scrapers",
                    "environment": [
                        {"name": "LAMBDA_INPUT", "value": json.dumps(event)},
                        {"name": "ECS_RUN_TASK", "value": "True"},
                    ],
                },
            ]
        },
    )

    print(response)
    logger.info(response)
    return None
