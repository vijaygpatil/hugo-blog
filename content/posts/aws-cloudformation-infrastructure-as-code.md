---
title: "AWS CloudFormation: Infrastructure as Code for Microservices"
date: 2022-11-10
draft: false
tags: ["aws", "cloudformation", "infrastructure", "devops", "microservices", "iac"]
description: "A practical guide to writing and deploying CloudFormation templates for a microservice — covering S3, SQS, IAM, and CloudWatch with real examples, parameter files, and a deployment workflow that works across environments."
---

If you have been building microservices on AWS for a few years, you know the drill: you provision an S3 bucket through the console for the first time, then do it again for staging, then again for prod, and six months later nobody remembers exactly what settings were applied where, or why. CloudFormation is the answer to that. It lets you describe your AWS infrastructure as code — version-controlled, repeatable, and reviewable.

This post walks through writing and deploying CloudFormation templates for the resources a typical microservice needs: S3, SQS, IAM, and CloudWatch. It assumes you are comfortable with AWS concepts and have used the CLI before, but have not written CloudFormation seriously. By the end you will have a working template structure you can adapt to your own service.

## What CloudFormation Actually Does

CloudFormation takes a template — a YAML or JSON file describing AWS resources — and turns it into a **stack**: a managed collection of those resources. When you update the template and redeploy, CloudFormation computes a **changeset** showing exactly what will be created, modified, or deleted before anything happens. When you delete the stack, all the resources in it are cleaned up (unless you tell it otherwise).

The core value is not just automation. It is that your infrastructure lives in your repository alongside your application code. A pull request that adds an SQS queue also adds the CloudFormation template that provisions it. New engineers can read the template to understand what the service depends on. Drift between environments becomes visible.

## Template Anatomy

Every CloudFormation template follows the same structure:

```yaml
AWSTemplateFormatVersion: '2010-09-09'
Description: 'Brief description of what this template provisions'

Parameters:
  # Inputs that let you reuse the template across environments

Conditions:
  # Boolean expressions derived from parameters

Resources:
  # The actual AWS resources — this section is mandatory

Outputs:
  # Values to export for use by other stacks or scripts
```

Only `Resources` is required. Everything else is optional, but `Parameters` and `Conditions` are what make a single template work across integration, staging, and production.

## Parameters: One Template, Many Environments

Parameters are how you inject environment-specific values without duplicating the template. You define them in the template and supply the actual values in a separate parameter file at deploy time.

```yaml
Parameters:
  Environment:
    Type: String
    Description: Deployment environment
    AllowedValues:
      - integration
      - staging
      - production

  ServiceName:
    Type: String
    Description: Name of the microservice, used as a prefix for resource names

  RetentionDays:
    Type: Number
    Default: 30
    Description: Log retention period in days
```

The corresponding parameter file — one per environment — looks like this:

```json
[
  { "ParameterKey": "Environment",   "ParameterValue": "integration" },
  { "ParameterKey": "ServiceName",   "ParameterValue": "my-service"  },
  { "ParameterKey": "RetentionDays", "ParameterValue": "7"           }
]
```

Keep your parameter files in version control alongside the templates, in a structure like:

```
cloudformation/
├── s3/
│   ├── template.yml
│   ├── params-integration.json
│   └── params-production.json
├── sqs/
│   ├── template.yml
│   ├── params-integration.json
│   └── params-production.json
├── iam/
│   └── template.yml
└── cloudwatch/
    ├── template.yml
    └── params-integration.json
```

One template per resource type. Each template is small, focused, and easy to reason about. This is far more manageable than one giant template that provisions everything.

## Conditions: Environment-Specific Behaviour

Conditions let you create or configure resources differently depending on parameter values, without duplicating the template.

```yaml
Conditions:
  IsProduction: !Equals [ !Ref Environment, production ]
  IsIntegration: !Equals [ !Ref Environment, integration ]
```

You can then use these in resource definitions:

```yaml
Resources:
  MyBucket:
    Type: AWS::S3::Bucket
    DeletionPolicy: !If [ IsProduction, Retain, Delete ]
    Properties:
      VersioningConfiguration:
        Status: !If [ IsProduction, Enabled, Suspended ]
```

In production, the bucket is retained if the stack is deleted and versioning is on. In integration, the bucket is deleted with the stack and versioning is off. Same template, different behaviour.

## S3

A basic S3 bucket template with encryption, versioning, and a lifecycle policy:

```yaml
AWSTemplateFormatVersion: '2010-09-09'
Description: 'S3 bucket for my-service data storage'

Parameters:
  Environment:
    Type: String
    AllowedValues: [ integration, staging, production ]

  ServiceName:
    Type: String

Conditions:
  IsProduction: !Equals [ !Ref Environment, production ]

Resources:
  DataBucket:
    Type: AWS::S3::Bucket
    DeletionPolicy: !If [ IsProduction, Retain, Delete ]
    UpdateReplacePolicy: Retain
    Properties:
      BucketName: !Sub '${ServiceName}-data-${Environment}'
      VersioningConfiguration:
        Status: !If [ IsProduction, Enabled, Suspended ]
      BucketEncryption:
        ServerSideEncryptionConfiguration:
          - ServerSideEncryptionByDefault:
              SSEAlgorithm: AES256
      LifecycleConfiguration:
        Rules:
          - Id: ExpireOldVersions
            Status: Enabled
            NoncurrentVersionExpiration:
              NoncurrentDays: 90
      PublicAccessBlockConfiguration:
        BlockPublicAcls: true
        BlockPublicPolicy: true
        IgnorePublicAcls: true
        RestrictPublicBuckets: true
      Tags:
        - Key: Environment
          Value: !Ref Environment
        - Key: Service
          Value: !Ref ServiceName

  DataBucketPolicy:
    Type: AWS::S3::BucketPolicy
    Properties:
      Bucket: !Ref DataBucket
      PolicyDocument:
        Version: '2012-10-17'
        Statement:
          - Sid: DenyInsecureConnections
            Effect: Deny
            Principal: '*'
            Action: 's3:*'
            Resource:
              - !GetAtt DataBucket.Arn
              - !Sub '${DataBucket.Arn}/*'
            Condition:
              Bool:
                'aws:SecureTransport': false

Outputs:
  BucketName:
    Value: !Ref DataBucket
    Description: Name of the data bucket

  BucketArn:
    Value: !GetAtt DataBucket.Arn
    Description: ARN of the data bucket
```

A few things worth noting:

**`!Sub`** substitutes variable references into a string. `${ServiceName}-data-${Environment}` becomes `my-service-data-integration` when those parameters are supplied.

**`!Ref`** and **`!GetAtt`** reference resources within the same template. `!Ref DataBucket` returns the bucket name; `!GetAtt DataBucket.Arn` returns its ARN.

**`DeletionPolicy: Retain`** means if someone deletes the stack, the bucket is not deleted. Always use this for production buckets with real data. Without it, `aws cloudformation delete-stack` will attempt to delete the bucket — and fail if it has contents, leaving the stack in a broken state.

**`PublicAccessBlockConfiguration`** — always set all four to `true` unless you have a specific reason not to. The default is not as locked down as you might expect.

## SQS

A queue template with a dead-letter queue (DLQ) — any message that fails processing a set number of times gets moved to the DLQ rather than being lost or causing infinite retries:

```yaml
AWSTemplateFormatVersion: '2010-09-09'
Description: 'SQS queues for my-service event processing'

Parameters:
  Environment:
    Type: String
    AllowedValues: [ integration, staging, production ]

  ServiceName:
    Type: String

  MessageRetentionSeconds:
    Type: Number
    Default: 345600  # 4 days
    Description: How long messages are retained if not consumed

  MaxReceiveCount:
    Type: Number
    Default: 3
    Description: Number of times a message is delivered before moving to DLQ

Conditions:
  IsProduction: !Equals [ !Ref Environment, production ]

Resources:
  EventDeadLetterQueue:
    Type: AWS::SQS::Queue
    DeletionPolicy: !If [ IsProduction, Retain, Delete ]
    Properties:
      QueueName: !Sub '${ServiceName}-events-dlq-${Environment}'
      MessageRetentionPeriod: 1209600  # 14 days for DLQ — longer retention for investigation
      Tags:
        - Key: Environment
          Value: !Ref Environment
        - Key: Service
          Value: !Ref ServiceName

  EventQueue:
    Type: AWS::SQS::Queue
    DeletionPolicy: !If [ IsProduction, Retain, Delete ]
    Properties:
      QueueName: !Sub '${ServiceName}-events-${Environment}'
      MessageRetentionPeriod: !Ref MessageRetentionSeconds
      VisibilityTimeout: 300
      RedrivePolicy:
        deadLetterTargetArn: !GetAtt EventDeadLetterQueue.Arn
        maxReceiveCount: !Ref MaxReceiveCount
      Tags:
        - Key: Environment
          Value: !Ref Environment
        - Key: Service
          Value: !Ref ServiceName

Outputs:
  EventQueueUrl:
    Value: !Ref EventQueue
    Description: URL of the event queue

  EventQueueArn:
    Value: !GetAtt EventQueue.Arn
    Description: ARN of the event queue

  DeadLetterQueueUrl:
    Value: !Ref EventDeadLetterQueue
    Description: URL of the dead-letter queue
```

**`VisibilityTimeout`** is how long a message is hidden from other consumers after one consumer picks it up. Set this longer than your maximum processing time, or you will get duplicate deliveries when processing is slow.

**`RedrivePolicy`** wires up the DLQ. When a message has been received `maxReceiveCount` times without being deleted (i.e., acknowledged), SQS moves it to the dead-letter queue automatically. Always set up a DLQ in production — without one, poison messages loop forever.

## IAM

Your application needs a role to access the S3 bucket and SQS queue you just provisioned. The principle of least privilege: grant only what the service actually needs.

```yaml
AWSTemplateFormatVersion: '2010-09-09'
Description: 'IAM role for my-service application'

Parameters:
  Environment:
    Type: String
    AllowedValues: [ integration, staging, production ]

  ServiceName:
    Type: String

  DataBucketArn:
    Type: String
    Description: ARN of the S3 data bucket (from S3 stack output)

  EventQueueArn:
    Type: String
    Description: ARN of the SQS event queue (from SQS stack output)

Resources:
  ApplicationRole:
    Type: AWS::IAM::Role
    Properties:
      RoleName: !Sub '${ServiceName}-app-role-${Environment}'
      AssumeRolePolicyDocument:
        Version: '2012-10-17'
        Statement:
          - Effect: Allow
            Principal:
              Service: ec2.amazonaws.com  # or ecs-tasks.amazonaws.com for ECS
            Action: sts:AssumeRole
      Policies:
        - PolicyName: S3Access
          PolicyDocument:
            Version: '2012-10-17'
            Statement:
              - Effect: Allow
                Action:
                  - s3:GetObject
                  - s3:PutObject
                  - s3:DeleteObject
                Resource: !Sub '${DataBucketArn}/*'
              - Effect: Allow
                Action:
                  - s3:ListBucket
                Resource: !Ref DataBucketArn
        - PolicyName: SQSAccess
          PolicyDocument:
            Version: '2012-10-17'
            Statement:
              - Effect: Allow
                Action:
                  - sqs:ReceiveMessage
                  - sqs:DeleteMessage
                  - sqs:GetQueueAttributes
                  - sqs:SendMessage
                Resource: !Ref EventQueueArn
      Tags:
        - Key: Environment
          Value: !Ref Environment
        - Key: Service
          Value: !Ref ServiceName

Outputs:
  ApplicationRoleArn:
    Value: !GetAtt ApplicationRole.Arn
    Description: ARN of the application role
```

**Cross-stack references**: Notice that `DataBucketArn` and `EventQueueArn` are parameters here, not hardcoded. They come from the Outputs of the S3 and SQS stacks. This keeps the IAM template decoupled — you can update a bucket ARN without touching the IAM template structure.

Never use `Resource: '*'` in a production policy unless the action genuinely requires it (a small number of S3 actions, like `s3:ListAllMyBuckets`, have no resource-level scope). Wildcard resources are the most common IAM mistake and the one that causes the most damage when something goes wrong.

## CloudWatch Alarms

Alarms are often left until something breaks in production. Don't do that. Define them in the same deployment pipeline as the resources they monitor.

```yaml
AWSTemplateFormatVersion: '2010-09-09'
Description: 'CloudWatch alarms for my-service'

Parameters:
  Environment:
    Type: String
    AllowedValues: [ integration, staging, production ]

  ServiceName:
    Type: String

  EventQueueName:
    Type: String
    Description: Name of the SQS event queue to monitor

  DeadLetterQueueName:
    Type: String
    Description: Name of the dead-letter queue to monitor

  AlarmEmail:
    Type: String
    Description: Email address for alarm notifications

  DLQThreshold:
    Type: Number
    Default: 1
    Description: Number of messages in DLQ before alarming

Conditions:
  IsProduction: !Equals [ !Ref Environment, production ]

Resources:
  AlarmTopic:
    Type: AWS::SNS::Topic
    Properties:
      TopicName: !Sub '${ServiceName}-alarms-${Environment}'
      Subscription:
        - Protocol: email
          Endpoint: !Ref AlarmEmail

  DLQMessageAlarm:
    Type: AWS::CloudWatch::Alarm
    Properties:
      AlarmName: !Sub '${ServiceName}-dlq-messages-${Environment}'
      AlarmDescription: 'Messages appearing in dead-letter queue indicate processing failures'
      Namespace: AWS/SQS
      MetricName: ApproximateNumberOfMessagesVisible
      Dimensions:
        - Name: QueueName
          Value: !Ref DeadLetterQueueName
      Statistic: Sum
      Period: 300
      EvaluationPeriods: 1
      Threshold: !Ref DLQThreshold
      ComparisonOperator: GreaterThanOrEqualToThreshold
      TreatMissingData: notBreaching
      AlarmActions:
        - !Ref AlarmTopic
      OKActions:
        - !Ref AlarmTopic

  QueueDepthAlarm:
    Type: AWS::CloudWatch::Alarm
    Properties:
      AlarmName: !Sub '${ServiceName}-queue-depth-${Environment}'
      AlarmDescription: 'Queue depth is high — consumers may be falling behind'
      Namespace: AWS/SQS
      MetricName: ApproximateNumberOfMessagesVisible
      Dimensions:
        - Name: QueueName
          Value: !Ref EventQueueName
      Statistic: Average
      Period: 300
      EvaluationPeriods: 3
      Threshold: 1000
      ComparisonOperator: GreaterThanThreshold
      TreatMissingData: notBreaching
      AlarmActions:
        - !If [ IsProduction, !Ref AlarmTopic, !Ref AWS::NoValue ]

  OldestMessageAlarm:
    Type: AWS::CloudWatch::Alarm
    Properties:
      AlarmName: !Sub '${ServiceName}-message-age-${Environment}'
      AlarmDescription: 'Messages are not being consumed — oldest message age is too high'
      Namespace: AWS/SQS
      MetricName: ApproximateAgeOfOldestMessage
      Dimensions:
        - Name: QueueName
          Value: !Ref EventQueueName
      Statistic: Maximum
      Period: 300
      EvaluationPeriods: 2
      Threshold: 3600  # 1 hour in seconds
      ComparisonOperator: GreaterThanThreshold
      TreatMissingData: notBreaching
      AlarmActions:
        - !Ref AlarmTopic
```

**`TreatMissingData: notBreaching`** — when there are no messages in a queue, CloudWatch stops emitting the `ApproximateNumberOfMessagesVisible` metric. Without this setting, the alarm would fire because it sees missing data as a problem. For queue metrics, missing data means the queue is empty, which is fine.

**`AWS::NoValue`** is a special CloudFormation value that removes a property entirely when used with `!If`. In the `QueueDepthAlarm`, the `AlarmActions` list is populated in production but omitted in integration — the alarm still triggers and turns red, but no notification is sent in non-production environments.

## Deploying with the AWS CLI

With templates and parameter files in place, deployment is straightforward. The key concept is the **changeset**: you create it, review it, then execute it.

```bash
# Create or update a stack using a changeset
aws cloudformation deploy \
  --template-file cloudformation/s3/template.yml \
  --stack-name my-service-s3-integration \
  --parameter-overrides file://cloudformation/s3/params-integration.json \
  --capabilities CAPABILITY_NAMED_IAM \
  --no-execute-changeset

# Review the changeset before executing
aws cloudformation describe-change-set \
  --stack-name my-service-s3-integration \
  --change-set-name <changeset-name-from-above>

# Execute when satisfied
aws cloudformation execute-change-set \
  --stack-name my-service-s3-integration \
  --change-set-name <changeset-name-from-above>
```

`--capabilities CAPABILITY_NAMED_IAM` is required whenever your template creates IAM resources. CloudFormation requires you to explicitly acknowledge this because IAM changes can affect access across your entire account.

For a simpler deploy-and-execute in one step (appropriate for non-production environments or when you trust the changeset):

```bash
aws cloudformation deploy \
  --template-file cloudformation/s3/template.yml \
  --stack-name my-service-s3-integration \
  --parameter-overrides file://cloudformation/s3/params-integration.json \
  --capabilities CAPABILITY_NAMED_IAM
```

## A Deployment Script

Once you have multiple templates, a small shell script that deploys them in the right order (IAM last, since it references ARNs from other stacks) is worth having:

```bash
#!/bin/bash
set -euo pipefail

ENV=${1:-integration}
SERVICE=my-service

echo "Deploying CloudFormation stacks for ${SERVICE} in ${ENV}"

deploy_stack() {
  local template=$1
  local stack_name=$2
  local params=$3

  echo "→ Deploying stack: ${stack_name}"
  aws cloudformation deploy \
    --template-file "cloudformation/${template}/template.yml" \
    --stack-name "${stack_name}" \
    --parameter-overrides "file://cloudformation/${template}/params-${ENV}.json" \
    --capabilities CAPABILITY_NAMED_IAM \
    --tags Environment="${ENV}" Service="${SERVICE}"
}

# Deploy in dependency order
deploy_stack s3        "${SERVICE}-s3-${ENV}"        "s3"
deploy_stack sqs       "${SERVICE}-sqs-${ENV}"       "sqs"
deploy_stack iam       "${SERVICE}-iam-${ENV}"       "iam"
deploy_stack cloudwatch "${SERVICE}-cloudwatch-${ENV}" "cloudwatch"

echo "All stacks deployed."
```

Run it as:

```bash
./scripts/deploy-cfn.sh integration
./scripts/deploy-cfn.sh production
```

## Tagging

Every resource should have consistent tags. Tags are how you find resources, track costs, and understand what belongs to what when something goes wrong at 2am.

A standard tag set for a microservice:

```yaml
Tags:
  - Key: Service
    Value: !Ref ServiceName
  - Key: Environment
    Value: !Ref Environment
  - Key: Team
    Value: platform-engineering
  - Key: Repository
    Value: my-service
```

Define these as a parameter in each template and apply them to every resource. The discipline feels tedious until you are looking at an unfamiliar resource in the console three years later and the tags tell you exactly what it belongs to.

## Things That Will Catch You Out

**Stack drift** — if someone modifies a resource directly in the console after it was created by CloudFormation, the stack drifts out of sync with the template. `aws cloudformation detect-drift --stack-name <name>` will identify what changed. The fix is usually to update the template to match reality and redeploy, or to manually revert the console change.

**Circular dependencies** — if Stack A exports a value that Stack B imports, and Stack B exports a value that Stack A imports, you have a circular dependency and neither can deploy. Break it by passing values as parameters rather than using `Fn::ImportValue`.

**Stack deletion with retained resources** — if your stack has `DeletionPolicy: Retain` on some resources, deleting the stack leaves those resources orphaned. They will not appear in any stack but will continue to exist and incur costs. Keep a record of retained resources.

**Update rollback** — if a stack update fails partway through, CloudFormation rolls back to the previous state. Usually this works cleanly. Occasionally it does not and the stack ends up in `UPDATE_ROLLBACK_FAILED` — a state where you cannot update or delete the stack. You need to call `ContinueUpdateRollback` with resources skipped, which is not fun. Avoid this by testing in integration first.

---

CloudFormation has rough edges and the YAML can become verbose, but the discipline of treating infrastructure as code pays off at every stage of a service's life — during development when you need to spin up a clean environment, during incidents when you need to understand what exists, and during off-boarding when you need to know what to clean up. The templates above give you a working foundation. Start with one resource type, get the deployment working end to end in integration, then build out from there.
