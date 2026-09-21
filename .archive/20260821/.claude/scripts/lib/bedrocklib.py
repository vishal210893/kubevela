"""
AWS Bedrock operations for Claude Code.
Shared functionality for cross-model validation via the Bedrock converse API.
"""

import os
import random
import time

# boto3 is imported lazily to allow import-time usage without the dependency
# (e.g., for resolve_model / MODELS). The get_client() and converse() functions
# import boto3 on first call.

# Base model IDs -- NO region prefix. The correct prefix (us., eu., ap.) is
# added at runtime by resolve_model() based on the active AWS region.
MODELS = {
    # Amazon Nova
    'nova-pro':         'amazon.nova-pro-v1:0',
    'nova-lite':        'amazon.nova-lite-v1:0',
    'nova-premier':     'amazon.nova-premier-v1:0',
    # Meta Llama
    'llama4-scout':     'meta.llama4-scout-17b-instruct-v1:0',
    'llama4-maverick':  'meta.llama4-maverick-17b-instruct-v1:0',
    'llama3-3':         'meta.llama3-3-70b-instruct-v1:0',
    # Mistral
    'pixtral-large':    'mistral.pixtral-large-2502-v1:0',
    # OpenAI
    'gpt-oss-120b':     'openai.gpt-oss-120b-1:0',
    # Anthropic Claude
    'opus-4.8':         'anthropic.claude-opus-4-8',
    'sonnet-4.6':       'anthropic.claude-sonnet-4-6',
    'opus-4.6':         'anthropic.claude-opus-4-6-v1',
    'sonnet-4.5':       'anthropic.claude-sonnet-4-5-20250929-v1:0',
    'opus-4.5':         'anthropic.claude-opus-4-5-20251101-v1:0',
    'opus-4.1':         'anthropic.claude-opus-4-1-20250805-v1:0',
    'sonnet-4':         'anthropic.claude-sonnet-4-20250514-v1:0',
    'haiku-4.5':        'anthropic.claude-haiku-4-5-20251001-v1:0',
}

DEFAULT_MODEL = 'opus-4.8'  # Fallback; orchestrator should inherit session model

# Max output tokens per model alias. Sourced from AWS Bedrock model cards.
MODEL_MAX_TOKENS = {
    'nova-pro':         5000,
    'nova-lite':        10000,
    'nova-premier':     32768,
    'llama4-scout':     8192,
    'llama4-maverick':  8192,
    'llama3-3':         8192,
    'pixtral-large':    2000,
    'gpt-oss-120b':     8192,
    'opus-4.8':         32768,
    'sonnet-4.6':       32768,
    'opus-4.6':         32768,
    'sonnet-4.5':       32768,
    'opus-4.5':         32768,
    'opus-4.1':         32768,
    'sonnet-4':         32768,
    'haiku-4.5':        32768,
}
DEFAULT_MAX_TOKENS = 32768


def get_max_tokens(alias):
    return MODEL_MAX_TOKENS.get(alias, DEFAULT_MAX_TOKENS)


def _region_prefix(region):
    if not region:
        return ''
    geo = region.split('-')[0]
    if geo in ('us', 'eu', 'ap', 'ca', 'sa', 'me', 'af'):
        return f'{geo}.'
    import sys
    print(f"Warning: region '{region}' has unknown geo prefix '{geo}'. "
          f"Model ID will be unprefixed.", file=sys.stderr)
    return ''


def _detect_region(explicit_region=None, profile=None):
    if explicit_region:
        return explicit_region
    region = os.environ.get('AWS_REGION') or os.environ.get('AWS_DEFAULT_REGION')
    if region:
        return region
    try:
        import botocore.session
        if profile is None:
            profile = os.environ.get('AWS_PROFILE') or None
        if profile is not None and profile.strip() == '':
            profile = None
        bc_session = botocore.session.Session()
        if profile:
            bc_session.set_config_variable('profile', profile)
        profiles = bc_session.full_config.get('profiles', {})
        profile_config = profiles.get(profile or 'default', {})
        config_region = profile_config.get('region')
        if config_region:
            return config_region
        sso_region = profile_config.get('sso_region')
        if sso_region:
            return sso_region
    except Exception:
        pass
    return None


def resolve_model(alias_or_id, region=None, profile=None):
    if alias_or_id in MODELS:
        if region is None:
            region = _detect_region(profile=profile)
        prefix = _region_prefix(region)
        base_id = MODELS[alias_or_id]
        return alias_or_id, f'{prefix}{base_id}'
    return alias_or_id, alias_or_id


def get_client(region=None, profile=None):
    import boto3
    import botocore.config
    import botocore.exceptions

    if profile is not None and profile.strip() == '':
        profile = None
    region = _detect_region(region, profile=profile)
    if not region:
        raise RuntimeError(
            "AWS region could not be determined.\n"
            "Set the region via:\n"
            "  - --region <region> flag\n"
            "  - AWS_REGION or AWS_DEFAULT_REGION environment variable\n"
            "  - AWS CLI: aws configure (sets default region)\n"
            "  - AWS SSO config (region is part of the SSO profile)"
        )
    try:
        session = boto3.Session(profile_name=profile, region_name=region)
        config = botocore.config.Config(
            read_timeout=300,
            retries={'max_attempts': 0}
        )
        client = session.client('bedrock-runtime', config=config)
        return client
    except botocore.exceptions.NoCredentialsError:
        raise RuntimeError(
            "AWS credentials not found.\n"
            "Configure credentials via:\n"
            "  - AWS SSO: aws sso login\n"
            "  - Environment variables (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY)\n"
            "  - AWS CLI: aws configure\n"
            "  - IAM role (if running on AWS)"
        )
    except botocore.exceptions.ProfileNotFound as e:
        raise RuntimeError(
            f"AWS profile error: {e}\n"
            "This often happens when AWS_PROFILE is set to an empty or "
            "invalid value in the environment.\n"
            "Fix:\n"
            "  - Unset it: unset AWS_PROFILE\n"
            "  - Set a valid profile: --profile your-profile\n"
            "  - Or configure via: aws sso login / aws configure"
        )
    except botocore.exceptions.EndpointConnectionError:
        raise RuntimeError(
            f"Cannot connect to Bedrock in region '{region}'.\n"
            "Check your network connection and verify the region supports Bedrock.\n"
            "Specify a different region: --region <region>"
        )
    except ValueError as e:
        raise RuntimeError(
            f"Invalid AWS configuration: {e}\n"
            f"Current region: '{region or '(empty)'}'\n"
            "Set a valid region: --region <region>"
        )


def preflight(region=None, profile=None, model=None):
    import boto3
    import botocore.exceptions

    if profile is not None and profile.strip() == '':
        profile = None
    if os.environ.get('AWS_PROFILE', '').strip() == '':
        os.environ.pop('AWS_PROFILE', None)

    region = _detect_region(region, profile=profile)
    if not region:
        raise RuntimeError(
            "AWS region could not be determined.\n"
            "Set the region via:\n"
            "  - --region <region> flag\n"
            "  - AWS_REGION or AWS_DEFAULT_REGION environment variable\n"
            "  - AWS CLI: aws configure (sets default region)\n"
            "  - AWS SSO config (region is part of the SSO profile)"
        )

    bearer = os.environ.get('AWS_BEARER_TOKEN_BEDROCK', '').strip()
    if bearer and not profile:
        return {'ok': True, 'auth': 'bedrock_bearer_token', 'region': region}

    try:
        session = boto3.Session(profile_name=profile, region_name=region)
        sts = session.client('sts')
        identity = sts.get_caller_identity()
        result = {
            'ok': True, 'auth': 'sts',
            'account': identity['Account'], 'arn': identity['Arn'],
            'region': region,
        }
        if model:
            _, model_id = resolve_model(model, region=region, profile=profile)
            access = check_model_access(region=region, profile=profile, model_id=model_id)
            result['model_access'] = access
        return result
    except botocore.exceptions.NoCredentialsError:
        raise RuntimeError(
            "AWS credentials not found.\n"
            "Configure credentials via:\n"
            "  - AWS SSO: aws sso login\n"
            "  - Environment variables (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY)\n"
            "  - AWS CLI: aws configure\n"
            "  - IAM role (if running on AWS)"
        )
    except botocore.exceptions.ProfileNotFound as e:
        raise RuntimeError(
            f"AWS profile error: {e}\n"
            "This often happens when AWS_PROFILE is set to an empty or "
            "invalid value. Fix: unset AWS_PROFILE or --profile <name>"
        )
    except botocore.exceptions.ClientError as e:
        error_code = e.response['Error']['Code']
        if error_code == 'ExpiredTokenException':
            raise RuntimeError(
                "AWS credentials have expired.\n"
                "Refresh credentials via:\n"
                "  - AWS SSO: aws sso login\n"
                "  - Environment variables: update AWS_SESSION_TOKEN\n"
                "  - AWS CLI: aws configure"
            )
        raise RuntimeError(
            f"AWS credential check failed ({error_code}): {e}\n"
            "Configure credentials via:\n"
            "  - AWS SSO: aws sso login\n"
            "  - Environment variables (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY)\n"
            "  - AWS CLI: aws configure"
        )


def check_model_access(region=None, profile=None, model_id=None):
    import boto3
    import botocore.exceptions

    if model_id is None:
        _, model_id = resolve_model(DEFAULT_MODEL, region=region, profile=profile)

    result = {
        'streaming_ok': False, 'converse_ok': False,
        'scp_blocked': False, 'scp_details': None, 'error': None,
    }

    session = boto3.Session(
        profile_name=profile if profile and profile.strip() else None,
        region_name=region,
    )
    client = session.client('bedrock-runtime', region_name=region)

    try:
        client.converse(
            modelId=model_id,
            messages=[{'role': 'user', 'content': [{'text': 'Say ok'}]}],
            inferenceConfig={'maxTokens': 1},
        )
        result['converse_ok'] = True
    except botocore.exceptions.ClientError as e:
        code = e.response['Error']['Code']
        msg = str(e)
        if 'service_control_policy' in msg:
            result['error'] = f"Converse API also blocked by SCP: {msg}"
        elif code == 'AccessDeniedException':
            result['error'] = f"Converse access denied: {msg}"
        else:
            result['error'] = f"Converse failed ({code}): {msg}"

    import json as _json
    try:
        body = _json.dumps({
            'anthropic_version': 'bedrock-2023-05-31',
            'max_tokens': 1,
            'messages': [{'role': 'user', 'content': 'ok'}],
        })
        resp = client.invoke_model_with_response_stream(
            modelId=model_id, body=body, contentType='application/json',
        )
        for _ in resp['body']:
            pass
        result['streaming_ok'] = True
    except botocore.exceptions.ClientError as e:
        msg = str(e)
        if 'service_control_policy' in msg:
            result['scp_blocked'] = True
            import re
            scp_match = re.search(
                r'service control policy:\s*(arn:aws:organizations::\d+:policy/[\w-]+/service_control_policy/[\w-]+)', msg,
            )
            resource_match = re.search(r'on resource:\s*(arn:aws:bedrock:[^\s]+)', msg)
            details = []
            if scp_match:
                details.append(f"SCP: {scp_match.group(1)}")
            if resource_match:
                details.append(f"Denied resource: {resource_match.group(1)}")
            result['scp_details'] = '; '.join(details) if details else msg

    return result


def converse(client, model_id, system_prompt, user_prompt, max_tokens=32768, temperature=0.3, effort=None):
    import botocore.exceptions

    max_retries = 8
    last_error = None

    kwargs = {
        'modelId': model_id,
        'messages': [{'role': 'user', 'content': [{'text': user_prompt}]}],
        'system': [{'text': system_prompt}],
        'inferenceConfig': {'maxTokens': max_tokens, 'temperature': temperature},
    }
    if effort:
        kwargs['additionalModelRequestFields'] = {
            'thinking': {'type': 'adaptive', 'effort': effort},
        }

    for attempt in range(max_retries):
        try:
            response = client.converse(**kwargs)
            try:
                content = response['output']['message']['content']
                if not content:
                    raise RuntimeError(f"Model '{model_id}' returned empty content array.")
                output_text = None
                for block in content:
                    if 'text' in block:
                        output_text = block['text']
                        break
                if output_text is None:
                    block_types = [list(b.keys()) for b in content]
                    raise RuntimeError(
                        f"Model '{model_id}' returned no text content block. Block types: {block_types}"
                    )
            except (KeyError, IndexError) as e:
                raise RuntimeError(f"Unexpected response structure from model '{model_id}': {e}")
            usage = response.get('usage', {})
            return {
                'text': output_text,
                'input_tokens': usage.get('inputTokens', 0),
                'output_tokens': usage.get('outputTokens', 0),
            }

        except botocore.exceptions.NoCredentialsError as e:
            raise RuntimeError(
                "AWS credentials not found.\n"
                "Configure credentials via:\n"
                "  - AWS SSO: aws sso login\n"
                "  - Environment variables (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY)\n"
                "  - AWS CLI: aws configure\n"
                "  - IAM role (if running on AWS)"
            ) from e

        except botocore.exceptions.ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == 'ThrottlingException':
                last_error = e
                if attempt < max_retries - 1:
                    max_jitter = min(1.0 * (3 ** attempt), 30.0)
                    wait = random.uniform(0.5, max_jitter)
                    time.sleep(wait)
                    continue
                raise RuntimeError(
                    f"Bedrock throttling after {max_retries} retries.\n"
                    "The model is rate-limited. Try again shortly or use a different model."
                ) from last_error

            if error_code == 'AccessDeniedException':
                raise RuntimeError(
                    f"Access denied for model '{model_id}'.\n"
                    "Ensure your IAM policy includes:\n"
                    "  - bedrock:InvokeModel\n"
                    "And that you have requested model access in the Bedrock console."
                ) from e

            if error_code == 'ValidationException':
                msg = str(e)
                hint = ""
                if "on-demand throughput" in msg.lower() or "isn't supported" in msg.lower():
                    hint = (
                        "\n\nThis often means the model requires a cross-region "
                        "inference profile. The script adds the region prefix "
                        "automatically. If this still fails, check that the "
                        "model is enabled in your Bedrock console for your region."
                    )
                raise RuntimeError(
                    f"Model '{model_id}' validation error: {e}\n"
                    f"The model may not be available in your region "
                    f"or may require access to be granted.{hint}"
                ) from e

            raise RuntimeError(f"Bedrock API error ({error_code}): {e}") from e

        except (botocore.exceptions.EndpointConnectionError,
                botocore.exceptions.ReadTimeoutError) as e:
            last_error = e
            if attempt < max_retries - 1:
                max_jitter = min(1.0 * (3 ** attempt), 30.0)
                wait = random.uniform(0, max_jitter)
                time.sleep(wait)
                continue
            raise RuntimeError(
                f"Network error after {max_retries} retries for model '{model_id}': {e}\n"
                "Check your network connection and region setting."
            ) from last_error
