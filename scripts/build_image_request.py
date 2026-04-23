#!/usr/bin/env python3
"""Build and optionally execute provider-backed image generation requests."""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shlex
import sys
import time
from pathlib import Path
from typing import Any
from urllib import error, request
from urllib.parse import urlparse


PLACEHOLDER_RE = re.compile(r"\{\{([^{}]+)\}\}")
SKILL_DIR = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_DIR = SKILL_DIR / "output" / "generated-images"
DEFAULT_SECRETS_FILE = SKILL_DIR / "scripts" / "secrets.local.json"


class ConfigError(ValueError):
    """Raised when the provider config is invalid."""


def load_json(path: str) -> dict[str, Any]:
    data = json.loads(Path(path).read_text())
    if not isinstance(data, dict):
        raise ConfigError("Provider config must be a JSON object.")
    return data


def load_secrets(path: str | None) -> dict[str, Any]:
    if not path:
        return {}
    secrets_path = Path(path).expanduser()
    if not secrets_path.exists():
        return {}
    data = json.loads(secrets_path.read_text())
    if not isinstance(data, dict):
        raise ConfigError("Secrets file must be a JSON object.")
    return data


def parse_extra_pairs(pairs: list[str]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for pair in pairs:
        if "=" not in pair:
            raise ConfigError(f"Invalid --extra value '{pair}'. Expected key=value.")
        key, raw_value = pair.split("=", 1)
        key = key.strip()
        if not key:
            raise ConfigError("Extra keys cannot be empty.")
        result[key] = coerce_scalar(raw_value.strip())
    return result


def coerce_scalar(value: str) -> Any:
    lowered = value.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered == "null":
        return None
    try:
        if "." in value:
            return float(value)
        return int(value)
    except ValueError:
        return value


def deep_get(data: Any, path: str) -> Any:
    current = data
    for part in path.split("."):
        if isinstance(current, list):
            try:
                current = current[int(part)]
            except (ValueError, IndexError) as exc:
                raise ConfigError(f"Cannot resolve path '{path}'.") from exc
        elif isinstance(current, dict):
            if part not in current:
                raise ConfigError(f"Cannot resolve path '{path}'.")
            current = current[part]
        else:
            raise ConfigError(f"Cannot resolve path '{path}'.")
    return current


def maybe_deep_get(data: Any, path: str | None) -> Any:
    if not path:
        return None
    try:
        return deep_get(data, path)
    except ConfigError:
        return None


def resolve_token(token: str, context: dict[str, Any], *, allow_missing: bool = False) -> Any:
    token = token.strip()
    if token.startswith("env:"):
        env_name = token[4:]
        value = os.environ.get(env_name)
        if value is None:
            raise ConfigError(f"Environment variable '{env_name}' is not set.")
        return value
    if token.startswith("secret:"):
        secret_name = token[7:]
        secrets = context.get("secrets", {})
        value = maybe_deep_get(secrets, secret_name)
        if value is None:
            value = os.environ.get(secret_name)
        if value is None:
            secrets_file = context.get("secrets_file") or str(DEFAULT_SECRETS_FILE)
            raise ConfigError(f"Secret '{secret_name}' not found. Add it to {secrets_file}.")
        return value
    try:
        return deep_get(context, token)
    except ConfigError:
        if allow_missing:
            return None
        raise


def resolve_template(value: Any, context: dict[str, Any]) -> Any:
    if isinstance(value, dict):
        return {key: resolve_template(val, context) for key, val in value.items()}
    if isinstance(value, list):
        return [resolve_template(item, context) for item in value]
    if not isinstance(value, str):
        return value

    exact_match = PLACEHOLDER_RE.fullmatch(value)
    if exact_match:
        return resolve_token(exact_match.group(1), context, allow_missing=True)

    def replacer(match: re.Match[str]) -> str:
        token_value = resolve_token(match.group(1), context)
        if isinstance(token_value, (dict, list)):
            return json.dumps(token_value, ensure_ascii=False)
        return str(token_value)

    return PLACEHOLDER_RE.sub(replacer, value)


def compact(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned = {key: compact(val) for key, val in value.items()}
        return {key: val for key, val in cleaned.items() if val not in (None, "", [], {})}
    if isinstance(value, list):
        cleaned = [compact(item) for item in value]
        return [item for item in cleaned if item not in (None, "", [], {})]
    return value


def build_auth_headers(provider: dict[str, Any], context: dict[str, Any]) -> dict[str, str]:
    auth = provider.get("auth")
    if not auth:
        return {}

    auth_type = auth.get("type", "bearer")
    secret_name = auth.get("api_key_secret")
    env_name = auth.get("api_key_env")
    if secret_name:
        api_key = maybe_deep_get(context.get("secrets", {}), secret_name)
        if api_key is None:
            api_key = os.environ.get(secret_name)
    elif env_name:
        api_key = os.environ.get(env_name)
    else:
        raise ConfigError("Provider auth config must include 'api_key_secret' or 'api_key_env'.")
    if api_key is None:
        secret_source = secret_name or env_name
        secrets_file = context.get("secrets_file") or str(DEFAULT_SECRETS_FILE)
        raise ConfigError(f"API key '{secret_source}' not found. Add it to {secrets_file}.")

    header_name = auth.get("header_name", "Authorization")
    if auth_type == "bearer":
        prefix = auth.get("prefix", "Bearer ")
        return {header_name: f"{prefix}{api_key}"}
    if auth_type == "header":
        prefix = auth.get("prefix", "")
        return {header_name: f"{prefix}{api_key}"}

    raise ConfigError(f"Unsupported auth type '{auth_type}'.")


def build_context(
    provider: dict[str, Any],
    args: argparse.Namespace,
    extras: dict[str, Any],
    secrets: dict[str, Any],
    secrets_file: str,
    *,
    task_id: str | None = None,
) -> dict[str, Any]:
    defaults = provider.get("defaults", {})
    count = args.count if args.count is not None else defaults.get("count", 1)
    context: dict[str, Any] = {
        "provider_name": provider.get("provider_name"),
        "mode": args.mode,
        "prompt": args.prompt,
        "negative_prompt": args.negative_prompt,
        "model": args.model or defaults.get("model"),
        "size": args.size or defaults.get("size"),
        "aspect_ratio": args.aspect_ratio or defaults.get("aspect_ratio"),
        "resolution": args.resolution or defaults.get("resolution"),
        "count": count,
        "quality": args.quality or defaults.get("quality"),
        "style": args.style or defaults.get("style"),
        "output_format": args.output_format or defaults.get("output_format"),
        "reference_images": args.reference_image or [],
        "language": args.language,
        "task_id": task_id or args.task_id,
        "extra": extras,
        "secrets": secrets,
        "secrets_file": secrets_file,
    }
    context.update(extras)
    return compact(context)


def build_json_request_from_template(request_cfg: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    method = resolve_template(request_cfg.get("method", "POST"), context)
    url = resolve_template(request_cfg.get("url"), context)
    if not url:
        raise ConfigError("Request config must include a URL.")

    headers = resolve_template(request_cfg.get("headers", {}), context)
    body = resolve_template(request_cfg.get("body"), context)
    body = compact(body)
    if body == {}:
        body = None

    return {
        "method": method,
        "url": url,
        "headers": compact(headers),
        "body": body,
    }


def build_openai_compatible_request(
    provider: dict[str, Any], context: dict[str, Any], extras: dict[str, Any]
) -> dict[str, Any]:
    base_url = provider.get("base_url")
    if not base_url:
        raise ConfigError("openai_compatible providers require 'base_url'.")

    endpoint_path = provider.get("endpoint_path", "/images/generations")
    url = f"{base_url.rstrip('/')}{endpoint_path}"
    headers = {"Content-Type": "application/json"}
    headers.update(build_auth_headers(provider, context))

    body = {
        "model": context.get("model"),
        "prompt": context.get("prompt"),
        "n": context.get("count", 1),
        "size": context.get("size"),
        "quality": context.get("quality"),
        "style": context.get("style"),
    }
    body.update(extras)
    return {
        "method": "POST",
        "url": url,
        "headers": headers,
        "body": compact(body),
    }


def build_template_json_request(
    provider: dict[str, Any], context: dict[str, Any], _extras: dict[str, Any]
) -> dict[str, Any]:
    request_cfg = provider.get("request")
    if not isinstance(request_cfg, dict):
        raise ConfigError("template_json providers require a 'request' object.")
    return build_json_request_from_template(request_cfg, context)


def build_request(provider: dict[str, Any], context: dict[str, Any], extras: dict[str, Any]) -> dict[str, Any]:
    adapter = provider.get("adapter")
    if adapter == "openai_compatible":
        return build_openai_compatible_request(provider, context, extras)
    if adapter == "template_json":
        return build_template_json_request(provider, context, extras)
    raise ConfigError(f"Unsupported adapter '{adapter}'.")


def supports_task_queries(provider: dict[str, Any]) -> bool:
    return isinstance(provider.get("task_status_request"), dict)


def build_task_status_request(provider: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    request_cfg = provider.get("task_status_request")
    if not isinstance(request_cfg, dict):
        raise ConfigError("Provider does not define task_status_request.")
    if not context.get("task_id"):
        raise ConfigError("A task ID is required to build a task status request.")
    return build_json_request_from_template(request_cfg, context)


def redact_headers(headers: dict[str, Any]) -> dict[str, Any]:
    redacted: dict[str, Any] = {}
    for key, value in headers.items():
        if key.lower() in {"authorization", "x-api-key", "api-key"}:
            redacted[key] = "***REDACTED***"
        else:
            redacted[key] = value
    return redacted


def redact_request(request_spec: dict[str, Any]) -> dict[str, Any]:
    return {
        **request_spec,
        "headers": redact_headers(request_spec.get("headers", {})),
    }


def redact_context(context: dict[str, Any]) -> dict[str, Any]:
    redacted = dict(context)
    redacted.pop("secrets", None)
    return redacted


def build_curl_command(request_spec: dict[str, Any]) -> str:
    parts = [
        "curl",
        "-X",
        shlex.quote(str(request_spec["method"])),
        shlex.quote(str(request_spec["url"])),
    ]
    for key, value in request_spec.get("headers", {}).items():
        header = f"{key}: {value}"
        parts.extend(["-H", shlex.quote(header)])
    if request_spec.get("body") is not None:
        body = json.dumps(request_spec["body"], ensure_ascii=False)
        parts.extend(["-d", shlex.quote(body)])
    return " ".join(parts)


def response_value_is_present(value: Any) -> bool:
    return value not in (None, "", [], {})


def parse_response_from_config(response_cfg: dict[str, Any], response_body: Any) -> dict[str, Any]:
    parsed = {
        "task_id": maybe_deep_get(response_body, response_cfg.get("task_id_path")),
        "status": maybe_deep_get(response_body, response_cfg.get("status_path")),
        "progress": maybe_deep_get(response_body, response_cfg.get("progress_path")),
        "image_url": maybe_deep_get(response_body, response_cfg.get("image_url_path")),
        "b64_json": maybe_deep_get(response_body, response_cfg.get("b64_json_path")),
        "error": maybe_deep_get(response_body, response_cfg.get("error_path")),
    }

    if response_value_is_present(parsed["error"]):
        return {"kind": "error", **parsed, "value": parsed["error"]}
    if response_value_is_present(parsed["image_url"]):
        return {"kind": "image_url", **parsed, "value": parsed["image_url"]}
    if response_value_is_present(parsed["b64_json"]):
        return {"kind": "b64_json", **parsed, "value": parsed["b64_json"]}
    if response_value_is_present(parsed["task_id"]):
        return {"kind": "task_submission", **parsed, "value": parsed["task_id"]}
    if response_value_is_present(parsed["status"]):
        return {"kind": "task_status", **parsed, "value": parsed["status"]}
    return {"kind": "raw_response", **parsed, "value": response_body}


def parse_submission_response(provider: dict[str, Any], response_body: Any) -> dict[str, Any]:
    response_cfg = provider.get("submission_response") or provider.get("response", {})
    return parse_response_from_config(response_cfg, response_body)


def parse_task_response(provider: dict[str, Any], response_body: Any) -> dict[str, Any]:
    response_cfg = provider.get("task_response") or provider.get("response", {})
    return parse_response_from_config(response_cfg, response_body)


def execute_request(request_spec: dict[str, Any], timeout: int) -> Any:
    body = request_spec.get("body")
    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = request.Request(
        request_spec["url"],
        data=data,
        headers=request_spec.get("headers", {}),
        method=request_spec["method"],
    )
    try:
        with request.urlopen(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except error.HTTPError as exc:
        message = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {message}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"Network error: {exc.reason}") from exc

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def ensure_unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    counter = 1
    while True:
        candidate = path.with_name(f"{stem}-{counter}{suffix}")
        if not candidate.exists():
            return candidate
        counter += 1


def default_output_dir() -> Path:
    return DEFAULT_OUTPUT_DIR


def infer_filename_from_url(image_url: str) -> str | None:
    parsed = urlparse(image_url)
    name = Path(parsed.path).name
    return name or None


def build_generated_filename(parsed_result: dict[str, Any], provider_name: str, output_format: str | None) -> str:
    task_id = parsed_result.get("task_id")
    timestamp = int(time.time())
    suffix = f".{output_format}" if output_format else ".png"
    base = f"{provider_name or 'generated-image'}-{task_id or timestamp}"
    return f"{base}{suffix}"


def write_b64_output(parsed_result: dict[str, Any], output_path: Path) -> str:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(base64.b64decode(parsed_result["value"]))
    return str(output_path)


def download_image_url(image_url: str, output_path: Path, timeout: int) -> str:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    req = request.Request(
        image_url,
        headers={
            "Accept": "image/*,*/*;q=0.8",
            "User-Agent": "curl/8.7.1",
        },
        method="GET",
    )
    try:
        with request.urlopen(req, timeout=timeout) as response:
            output_path.write_bytes(response.read())
    except error.HTTPError as exc:
        message = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Failed to download image: HTTP {exc.code}: {message}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"Failed to download image: {exc.reason}") from exc
    return str(output_path)


def maybe_persist_result_asset(
    parsed_result: dict[str, Any],
    *,
    output_file: str | None,
    output_format: str | None,
    download_dir: str | None,
    provider_name: str,
    timeout: int,
) -> str | None:
    kind = parsed_result.get("kind")
    if kind not in {"b64_json", "image_url"}:
        return None

    if kind == "b64_json" and output_file:
        return write_b64_output(parsed_result, Path(output_file))
    if kind == "image_url" and output_file:
        raise ConfigError("--output-file 仅用于 base64 图片结果，图片 URL 请使用 --download-dir。")

    target_dir = Path(download_dir) if download_dir else default_output_dir()
    target_dir.mkdir(parents=True, exist_ok=True)

    if kind == "image_url":
        filename = infer_filename_from_url(parsed_result["value"]) or build_generated_filename(
            parsed_result,
            provider_name,
            output_format,
        )
        output_path = ensure_unique_path(target_dir / filename)
        return download_image_url(parsed_result["value"], output_path, timeout)

    filename = build_generated_filename(parsed_result, provider_name, output_format)
    output_path = ensure_unique_path(target_dir / filename)
    return write_b64_output(parsed_result, output_path)


def normalize_status(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip().lower()
    return str(value).strip().lower()


def get_status_sets(provider: dict[str, Any]) -> tuple[set[str], set[str]]:
    task_response = provider.get("task_response", {})
    success_values = task_response.get("success_status_values", ["completed", "succeeded", "success"])
    failure_values = task_response.get("failure_status_values", ["failed", "cancelled", "canceled", "error"])
    return ({normalize_status(item) for item in success_values}, {normalize_status(item) for item in failure_values})


def build_preview_output(
    provider: dict[str, Any],
    args: argparse.Namespace,
    context: dict[str, Any],
    request_spec: dict[str, Any],
    *,
    task_status_request: dict[str, Any] | None = None,
) -> dict[str, Any]:
    output = {
        "provider": provider.get("provider_name"),
        "adapter": provider.get("adapter"),
        "mode": args.mode,
        "normalized_inputs": redact_context(context),
        "request": redact_request(request_spec),
        "curl": build_curl_command(redact_request(request_spec)),
    }
    if task_status_request is not None:
        output["task_status_request"] = redact_request(task_status_request)
        output["task_status_curl"] = build_curl_command(redact_request(task_status_request))
    return output


def poll_task(
    provider: dict[str, Any],
    args: argparse.Namespace,
    extras: dict[str, Any],
    *,
    task_id: str,
) -> tuple[dict[str, Any], Any, dict[str, Any]]:
    success_values, failure_values = get_status_sets(provider)
    deadline = time.time() + args.poll_timeout
    latest_response: Any = None
    latest_parsed: dict[str, Any] = {"kind": "raw_response", "value": None}
    latest_request: dict[str, Any] | None = None

    while True:
        status_context = build_context(
            provider,
            args,
            extras,
            load_secrets(args.secrets_file),
            str(Path(args.secrets_file).expanduser()),
            task_id=task_id,
        )
        latest_request = build_task_status_request(provider, status_context)
        latest_response = execute_request(latest_request, args.timeout)
        latest_parsed = parse_task_response(provider, latest_response)
        normalized_status = normalize_status(latest_parsed.get("status"))

        if normalized_status in success_values or latest_parsed.get("kind") in {"image_url", "b64_json"}:
            return latest_parsed, latest_response, latest_request

        if normalized_status in failure_values or latest_parsed.get("kind") == "error":
            detail = latest_parsed.get("error") or latest_response
            raise RuntimeError(f"Task {task_id} failed: {detail}")

        if time.time() >= deadline:
            raise RuntimeError(
                f"Polling timed out after {args.poll_timeout}s for task {task_id}. "
                f"Last known status: {latest_parsed.get('status')!r}"
            )

        time.sleep(args.poll_interval)


def validate_args(args: argparse.Namespace, provider: dict[str, Any]) -> None:
    if not args.task_id and not args.prompt:
        raise ConfigError("--prompt is required unless --task-id is provided.")
    if args.task_id and not supports_task_queries(provider):
        raise ConfigError("This provider config does not support task status queries.")
    if args.poll and not supports_task_queries(provider):
        raise ConfigError("--poll requires a provider config with task_status_request.")


def maybe_save_request(output: dict[str, Any], save_request: str | None) -> None:
    if not save_request:
        return
    request_path = Path(save_request)
    request_path.parent.mkdir(parents=True, exist_ok=True)
    request_path.write_text(json.dumps(output, indent=2, ensure_ascii=False))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build or execute a provider-backed image generation request."
    )
    parser.add_argument("--config", required=True, help="Path to provider JSON config.")
    parser.add_argument("--prompt", help="Final image prompt.")
    parser.add_argument(
        "--mode",
        default="generate",
        choices=["generate", "edit", "variation"],
        help="Logical request mode.",
    )
    parser.add_argument("--task-id", help="Query an existing async task instead of submitting a new request.")
    parser.add_argument("--language", default="zh", help="Language for async task status queries.")
    parser.add_argument("--model", help="Override the provider default model.")
    parser.add_argument("--size", help="Explicit image size such as 1024x1024 or 16:9.")
    parser.add_argument("--aspect-ratio", help="Aspect ratio such as 1:1 or 16:9.")
    parser.add_argument("--resolution", help="Provider-specific resolution tier such as 2k.")
    parser.add_argument("--count", type=int, help="Number of images to request.")
    parser.add_argument("--quality", help="Provider-specific quality hint.")
    parser.add_argument("--style", help="Provider-specific style hint.")
    parser.add_argument("--output-format", help="Provider-specific output format hint.")
    parser.add_argument("--negative-prompt", help="Optional negative prompt.")
    parser.add_argument(
        "--reference-image",
        action="append",
        default=[],
        help="Reference image path, URL, or vendor-specific handle. Repeatable.",
    )
    parser.add_argument(
        "--extra",
        action="append",
        default=[],
        help="Provider-specific key=value pairs. Repeatable.",
    )
    parser.add_argument(
        "--save-request",
        help="Write the resolved request and redacted headers to a JSON file.",
    )
    parser.add_argument(
        "--secrets-file",
        default=str(DEFAULT_SECRETS_FILE),
        help="本地密钥 JSON 文件路径，默认读取 scripts/secrets.local.json。",
    )
    parser.add_argument("--execute", action="store_true", help="Execute the request.")
    parser.add_argument(
        "--poll",
        action="store_true",
        help="After submitting an async task, poll until it reaches a terminal state.",
    )
    parser.add_argument(
        "--poll-interval",
        type=int,
        default=5,
        help="Polling interval in seconds for async task queries.",
    )
    parser.add_argument(
        "--poll-timeout",
        type=int,
        default=300,
        help="Maximum time in seconds to wait for async task completion.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=120,
        help="HTTP timeout in seconds for each request.",
    )
    parser.add_argument(
        "--output-file",
        help="Write decoded base64 image output to this file when available.",
    )
    parser.add_argument(
        "--download-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="保存最终图片的本地目录。对图片 URL 结果会自动下载到这里；默认是 skill 下的 output/generated-images。",
    )
    args = parser.parse_args()

    try:
        provider = load_json(args.config)
        validate_args(args, provider)
        extras = parse_extra_pairs(args.extra)
        secrets_file = str(Path(args.secrets_file).expanduser())
        secrets = load_secrets(secrets_file)

        if args.task_id:
            status_context = build_context(provider, args, extras, secrets, secrets_file)
            status_request = build_task_status_request(provider, status_context)
            output = build_preview_output(
                provider,
                args,
                status_context,
                status_request,
            )
            maybe_save_request(output, args.save_request)

            if not args.execute:
                print(json.dumps(output, indent=2, ensure_ascii=False))
                return 0

            response_body = execute_request(status_request, args.timeout)
            parsed = parse_task_response(provider, response_body)
            saved_path = maybe_persist_result_asset(
                parsed,
                output_file=args.output_file,
                output_format=status_context.get("output_format"),
                download_dir=args.download_dir,
                provider_name=provider.get("provider_name", "generated-image"),
                timeout=args.timeout,
            )
            result = {
                **output,
                "result": parsed,
            }
            if saved_path:
                result["saved_file"] = saved_path
            print(json.dumps(result, indent=2, ensure_ascii=False))
            return 0

        context = build_context(provider, args, extras, secrets, secrets_file)
        request_spec = build_request(provider, context, extras)
        preview = build_preview_output(provider, args, context, request_spec)
        maybe_save_request(preview, args.save_request)

        if not args.execute:
            print(json.dumps(preview, indent=2, ensure_ascii=False))
            return 0

        response_body = execute_request(request_spec, args.timeout)
        parsed = parse_submission_response(provider, response_body)

        result = {
            **preview,
            "result": parsed,
        }

        if supports_task_queries(provider) and parsed.get("task_id"):
            status_context = build_context(
                provider,
                args,
                extras,
                secrets,
                secrets_file,
                task_id=parsed["task_id"],
            )
            status_request = build_task_status_request(provider, status_context)
            result["task_status_request"] = redact_request(status_request)
            result["task_status_curl"] = build_curl_command(redact_request(status_request))

        if args.poll and parsed.get("task_id"):
            polled_result, poll_response, poll_request = poll_task(
                provider,
                args,
                extras,
                task_id=parsed["task_id"],
            )
            saved_path = maybe_persist_result_asset(
                polled_result,
                output_file=args.output_file,
                output_format=context.get("output_format"),
                download_dir=args.download_dir,
                provider_name=provider.get("provider_name", "generated-image"),
                timeout=args.timeout,
            )
            result["polled_status_request"] = redact_request(poll_request)
            result["polled_status_response"] = poll_response
            result["polled_result"] = polled_result
            if saved_path:
                result["saved_file"] = saved_path
        else:
            saved_path = maybe_persist_result_asset(
                parsed,
                output_file=args.output_file,
                output_format=context.get("output_format"),
                download_dir=args.download_dir,
                provider_name=provider.get("provider_name", "generated-image"),
                timeout=args.timeout,
            )
            if saved_path:
                result["saved_file"] = saved_path

        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except (ConfigError, RuntimeError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
