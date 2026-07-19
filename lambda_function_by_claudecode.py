import boto3
from datetime import datetime, timezone

ec2 = boto3.client('ec2')
sns = boto3.client('sns')

TOPIC_ARN = "arn:aws:sns:ap-southeast-2:YOUR_ACCOUNT_ID:snapshots"
IDLE_THRESHOLD_DAYS = 20

def lambda_handler(event, context):
    # Store deleted snapshot IDs
    deleted_snapshots = []

    # Get all EBS snapshots
    response = ec2.describe_snapshots(OwnerIds=['self'])

    # Get all active EC2 instance IDs
    instances_response = ec2.describe_instances(
        Filters=[{'Name': 'instance-state-name', 'Values': ['running']}]
    )
    active_instance_ids = set()

    for reservation in instances_response['Reservations']:
        for instance in reservation['Instances']:
            active_instance_ids.add(instance['InstanceId'])

    # Iterate through each snapshot
    for snapshot in response['Snapshots']:
        snapshot_id = snapshot['SnapshotId']
        volume_id = snapshot.get('VolumeId')
        start_time = snapshot['StartTime']

        # Skip snapshots that haven't crossed the idle threshold yet
        age_days = (datetime.now(timezone.utc) - start_time).days
        if age_days < IDLE_THRESHOLD_DAYS:
            continue

        if not volume_id:
            ec2.delete_snapshot(SnapshotId=snapshot_id)
            deleted_snapshots.append(snapshot_id)
            print(f"Deleted EBS snapshot {snapshot_id} as it was not attached to any volume and idle for {age_days} days.")

        else:
            try:
                volume_response = ec2.describe_volumes(VolumeIds=[volume_id])

                if not volume_response['Volumes'][0]['Attachments']:
                    ec2.delete_snapshot(SnapshotId=snapshot_id)
                    deleted_snapshots.append(snapshot_id)
                    print(f"Deleted EBS snapshot {snapshot_id} as it was taken from a volume not attached to any running instance and idle for {age_days} days.")

            except ec2.exceptions.ClientError as e:
                if e.response['Error']['Code'] == 'InvalidVolume.NotFound':
                    ec2.delete_snapshot(SnapshotId=snapshot_id)
                    deleted_snapshots.append(snapshot_id)
                    print(f"Deleted EBS snapshot {snapshot_id} as its associated volume was not found and idle for {age_days} days.")

    # Send one email if any snapshots were deleted
    if deleted_snapshots:
        sns.publish(
            TopicArn=TOPIC_ARN,
            Subject="EBS Snapshot Cleanup Report",
            Message="The following snapshots were deleted:\n\n" + "\n".join(deleted_snapshots)
        )

    return {
        "statusCode": 200,
        "body": f"Deleted {len(deleted_snapshots)} snapshot(s)."
    }
