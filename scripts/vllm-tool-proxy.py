#!/usr/bin/env python3
"""
═══════════════════════════════════════════════════════════════
Local Claw Plus Session Manager - vLLM Tool Call Proxy
https://github.com/Lightheartdevs/Local-Claw-Plus-Session-Manager

Makes local model tool calling actually work.

Problem:
  Qwen2.5-Coder (and similar models) output tool calls as
  <tools>{"name":"func","arguments":{...}}</tools> tags inside
  the content field. vLLM's built-in hermes parser expects
  <tool_call> tags and misses them entirely. The result:
  subagents spawn, get no tool calls, and die immediately.

Solution:
  This proxy sits between OpenClaw and vLLM. It:
  1. Forwards all requests to vLLM unchanged
  2. Post-processes responses to extract tool calls from
     <tools> tags (and bare JSON) in the content field
  3. Converts them to proper OpenAI tool_calls format
  4. Handles both streaming (SSE) and non-streaming responses

Supported models:
  - Qwen2.5-Coder (all sizes)
  - Qwen2.5 Instruct (all sizes)
  - Any model that outputs <tools> tags for function calling
  - Models that output bare JSON tool calls in content

Usage:
  python3 vllm-tool-proxy.py --port 8003 --vllm-url http://localhost:8000

  Then point OpenClaw providers to http://localhost:8003/v1
  instead of http://localhost:8000/v1
═══════════════════════════════════════════════════════════════
"""
import argparse
import json
import logging
import re
import uuid
from flask import Flask, request, Response
import requests

app = Flask(__name__)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s: %(message)s'
)
logger = logging.getLogger(__name__)

VLLM_URL = 'http://localhost:8000'

# Matches <tools>...</tools> blocks containing tool call JSON
TOOLS_REGEX = re.compile(r'<tools>(.*?)</tools>', re.DOTALL)


# ═══════════════════════════════════════════════════════════════
# Tool Extraction - Non-Streaming
# ═══════════════════════════════════════════════════════════════

def extract_tools_from_content(response_json):
    """
    Post-process a non-streaming response.
    If tool_calls is empty but content contains tool JSON, extract and fix it.
    """
    try:
        choices = response_json.get('choices', [])
        for choice in choices:
            msg = choice.get('message', {})
            content = msg.get('content', '') or ''
            tool_calls = msg.get('tool_calls') or []

            # Skip if already has tool calls or no content
            if tool_calls or not content.strip():
                continue

            extracted_calls = []

            # Strategy 1: Extract from <tools> tags
            matches = TOOLS_REGEX.findall(content)
            if matches:
                for match in matches:
                    for line in match.strip().split('\n'):
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            call = json.loads(line)
                            if 'name' in call:
                                args = call.get('arguments', {})
                                if isinstance(args, dict):
                                    args = json.dumps(args)
                                extracted_calls.append({
                                    'id': f'chatcmpl-tool-{uuid.uuid4().hex[:16]}',
                                    'type': 'function',
                                    'function': {
                                        'name': call['name'],
                                        'arguments': args
                                    }
                                })
                        except json.JSONDecodeError:
                            continue

            # Strategy 2: Try bare JSON (model sometimes outputs without tags)
            if not extracted_calls:
                stripped = content.strip()
                try:
                    call = json.loads(stripped)
                    if isinstance(call, dict) and 'name' in call:
                        args = call.get('arguments', {})
                        if isinstance(args, dict):
                            args = json.dumps(args)
                        extracted_calls.append({
                            'id': f'chatcmpl-tool-{uuid.uuid4().hex[:16]}',
                            'type': 'function',
                            'function': {
                                'name': call['name'],
                                'arguments': args
                            }
                        })
                except (json.JSONDecodeError, ValueError):
                    pass

            if extracted_calls:
                logger.info(f'Extracted {len(extracted_calls)} tool call(s) from content')

                # Clean the content (remove tool tags, keep any text around them)
                cleaned = TOOLS_REGEX.sub('', content).strip()
                # If cleaned content is just JSON, null it out
                try:
                    json.loads(cleaned)
                    cleaned = None
                except (json.JSONDecodeError, ValueError):
                    pass

                msg['content'] = cleaned if cleaned else None
                msg['tool_calls'] = extracted_calls
                choice['finish_reason'] = 'tool_calls'
    except Exception as e:
        logger.error(f'Error in tool extraction: {e}')


# ═══════════════════════════════════════════════════════════════
# Tool Extraction - Streaming (SSE)
# ═══════════════════════════════════════════════════════════════

def extract_tools_from_streaming_chunks(raw_chunks):
    """
    Reassemble streaming SSE chunks, check for tool calls,
    and re-emit as properly formatted SSE.

    This buffers the full response first (necessary because we can't
    know if content contains tool calls until we see all of it),
    then either yields the original chunks or re-emits with tool_calls.
    """
    full_content = ''
    last_chunk_data = None
    chunk_id = None
    chunk_model = None
    all_raw = []

    # Buffer all chunks and reconstruct content
    for raw in raw_chunks:
        all_raw.append(raw)
        text = raw.decode('utf-8', errors='replace') if isinstance(raw, bytes) else raw
        for line in text.split('\n'):
            line = line.strip()
            if not line.startswith('data: '):
                continue
            data_str = line[6:]
            if data_str == '[DONE]':
                continue
            try:
                data = json.loads(data_str)
                if not chunk_id:
                    chunk_id = data.get('id')
                    chunk_model = data.get('model')
                choices = data.get('choices', [])
                for c in choices:
                    delta = c.get('delta', {})
                    if 'content' in delta and delta['content']:
                        full_content += delta['content']
                last_chunk_data = data
            except json.JSONDecodeError:
                continue

    # Check if content has tool calls
    has_tools = bool(TOOLS_REGEX.search(full_content))
    bare_json_tool = False
    if not has_tools and full_content.strip():
        try:
            call = json.loads(full_content.strip())
            if isinstance(call, dict) and 'name' in call:
                bare_json_tool = True
                has_tools = True
        except (json.JSONDecodeError, ValueError):
            pass

    if not has_tools:
        # No tools found, yield original chunks unchanged
        for raw in all_raw:
            yield raw
        return

    # Extract tool calls
    logger.info(f'Extracting tool calls from streaming content ({len(full_content)} chars)')

    extracted_calls = []

    # From <tools> tags
    matches = TOOLS_REGEX.findall(full_content)
    if matches:
        for match in matches:
            for line in match.strip().split('\n'):
                line = line.strip()
                if not line:
                    continue
                try:
                    call = json.loads(line)
                    if 'name' in call:
                        args = call.get('arguments', {})
                        if isinstance(args, dict):
                            args = json.dumps(args)
                        extracted_calls.append({
                            'id': f'chatcmpl-tool-{uuid.uuid4().hex[:16]}',
                            'type': 'function',
                            'function': {
                                'name': call['name'],
                                'arguments': args
                            }
                        })
                except json.JSONDecodeError:
                    continue

    # From bare JSON
    elif bare_json_tool:
        call = json.loads(full_content.strip())
        args = call.get('arguments', {})
        if isinstance(args, dict):
            args = json.dumps(args)
        extracted_calls.append({
            'id': f'chatcmpl-tool-{uuid.uuid4().hex[:16]}',
            'type': 'function',
            'function': {
                'name': call['name'],
                'arguments': args
            }
        })

    if not extracted_calls:
        # Extraction failed, yield originals
        for raw in all_raw:
            yield raw
        return

    logger.info(f'Extracted {len(extracted_calls)} tool call(s) from stream')

    created = last_chunk_data.get('created', 0) if last_chunk_data else 0
    base_id = chunk_id or f'chatcmpl-{uuid.uuid4().hex[:12]}'

    # Re-emit as proper streaming tool_calls delta chunks
    for i, tc in enumerate(extracted_calls):
        # Chunk 1: tool_call with function name
        delta_data = {
            'id': base_id,
            'object': 'chat.completion.chunk',
            'created': created,
            'model': chunk_model or '',
            'choices': [{
                'index': 0,
                'delta': {
                    'tool_calls': [{
                        'index': i,
                        'id': tc['id'],
                        'type': 'function',
                        'function': {
                            'name': tc['function']['name'],
                            'arguments': ''
                        }
                    }]
                },
                'finish_reason': None
            }]
        }
        yield f'data: {json.dumps(delta_data)}\n\n'.encode()

        # Chunk 2: arguments payload
        args_data = {
            'id': base_id,
            'object': 'chat.completion.chunk',
            'created': created,
            'model': chunk_model or '',
            'choices': [{
                'index': 0,
                'delta': {
                    'tool_calls': [{
                        'index': i,
                        'function': {
                            'arguments': tc['function']['arguments']
                        }
                    }]
                },
                'finish_reason': None
            }]
        }
        yield f'data: {json.dumps(args_data)}\n\n'.encode()

    # Final chunk: finish_reason
    done_data = {
        'id': base_id,
        'object': 'chat.completion.chunk',
        'created': created,
        'model': chunk_model or '',
        'choices': [{
            'index': 0,
            'delta': {},
            'finish_reason': 'tool_calls'
        }]
    }
    yield f'data: {json.dumps(done_data)}\n\n'.encode()
    yield b'data: [DONE]\n\n'


# ═══════════════════════════════════════════════════════════════
# Request Handlers
# ═══════════════════════════════════════════════════════════════

@app.route('/v1/<path:path>', methods=['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS'])
def proxy(path):
    url = f'{VLLM_URL}/v1/{path}'

    if request.method == 'OPTIONS':
        return Response('', status=204)

    # Only intercept chat completions
    if path not in ('chat/completions',):
        return forward_request(url)

    try:
        body = request.get_json()
    except Exception:
        body = None

    has_tools = body and body.get('tools')
    is_streaming = body.get('stream', False) if body else False
    headers = {
        k: v for k, v in request.headers
        if k.lower() not in ('host', 'content-length')
    }

    if not has_tools:
        # No tools in request, just forward
        if is_streaming:
            return stream_passthrough(url, headers, body)
        else:
            return forward_with_body(url, headers, body)

    # Has tools — intercept and fix
    if is_streaming:
        return stream_with_tool_extraction(url, headers, body)
    else:
        return forward_with_body_and_fix(url, headers, body)


def forward_request(url):
    """Forward any request as-is (non-chat endpoints)."""
    headers = {
        k: v for k, v in request.headers
        if k.lower() not in ('host', 'content-length')
    }
    try:
        resp = requests.request(
            method=request.method, url=url, headers=headers,
            data=request.get_data(), stream=True, timeout=300
        )
        excluded = {'content-encoding', 'transfer-encoding', 'content-length'}
        resp_headers = {
            k: v for k, v in resp.headers.items()
            if k.lower() not in excluded
        }
        return Response(
            resp.iter_content(chunk_size=1024),
            status=resp.status_code,
            headers=resp_headers
        )
    except Exception as e:
        logger.error(f'Forward error: {e}')
        return Response(
            json.dumps({'error': str(e)}),
            status=502,
            mimetype='application/json'
        )


def forward_with_body(url, headers, body):
    """Forward with JSON body, no tool extraction."""
    try:
        resp = requests.post(url, headers=headers, json=body, timeout=300)
        return Response(
            resp.content,
            status=resp.status_code,
            mimetype='application/json'
        )
    except Exception as e:
        logger.error(f'Forward error: {e}')
        return Response(
            json.dumps({'error': str(e)}),
            status=502,
            mimetype='application/json'
        )


def forward_with_body_and_fix(url, headers, body):
    """Forward with JSON body, then extract tools from response."""
    try:
        resp = requests.post(url, headers=headers, json=body, timeout=300)
        try:
            resp_json = resp.json()
            extract_tools_from_content(resp_json)
            return Response(
                json.dumps(resp_json),
                status=resp.status_code,
                mimetype='application/json'
            )
        except Exception:
            return Response(resp.content, status=resp.status_code)
    except Exception as e:
        logger.error(f'Forward error: {e}')
        return Response(
            json.dumps({'error': str(e)}),
            status=502,
            mimetype='application/json'
        )


def stream_passthrough(url, headers, body):
    """Stream response through without modification."""
    def generate():
        try:
            with requests.post(url, headers=headers, json=body,
                               stream=True, timeout=300) as resp:
                for chunk in resp.iter_content(chunk_size=None):
                    if chunk:
                        yield chunk
        except Exception as e:
            logger.error(f'Stream error: {e}')
            yield f'data: {json.dumps({"error": str(e)})}\n\n'.encode()

    return Response(generate(), mimetype='text/event-stream')


def stream_with_tool_extraction(url, headers, body):
    """Buffer full stream, extract tools if present, re-emit."""
    def generate():
        raw_chunks = []
        try:
            with requests.post(url, headers=headers, json=body,
                               stream=True, timeout=300) as resp:
                for chunk in resp.iter_content(chunk_size=None):
                    if chunk:
                        raw_chunks.append(chunk)
        except Exception as e:
            logger.error(f'Stream error: {e}')
            yield f'data: {json.dumps({"error": str(e)})}\n\n'.encode()
            return

        for processed in extract_tools_from_streaming_chunks(raw_chunks):
            yield processed

    return Response(generate(), mimetype='text/event-stream')


# ═══════════════════════════════════════════════════════════════
# Health & Info
# ═══════════════════════════════════════════════════════════════

@app.route('/health')
def health():
    return {'status': 'ok', 'vllm_url': VLLM_URL}


@app.route('/')
def root():
    return {
        'service': 'Local Claw Plus Session Manager - vLLM Tool Call Proxy',
        'version': '2.0.0',
        'vllm_url': VLLM_URL,
        'supported_models': [
            'Qwen2.5-Coder (all sizes)',
            'Qwen2.5 Instruct (all sizes)',
            'Any model outputting <tools> tags',
            'Models outputting bare JSON tool calls'
        ],
        'features': [
            'Extracts tool calls from <tools> tags (non-streaming)',
            'Extracts tool calls from <tools> tags (streaming/SSE)',
            'Extracts tool calls from bare JSON in content',
            'No forced tool_choice (prevents terminated/0-token errors)',
            'Passthrough for non-tool requests (zero overhead)'
        ]
    }


# ═══════════════════════════════════════════════════════════════
# Entry Point
# ═══════════════════════════════════════════════════════════════

if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='vLLM Tool Call Proxy - Makes local model tool calling work'
    )
    parser.add_argument('--port', type=int, default=8003,
                        help='Port to listen on (default: 8003)')
    parser.add_argument('--vllm-url', type=str, default='http://localhost:8000',
                        help='vLLM server URL (default: http://localhost:8000)')
    parser.add_argument('--host', type=str, default='0.0.0.0',
                        help='Bind address (default: 0.0.0.0)')
    args = parser.parse_args()

    VLLM_URL = args.vllm_url
    logger.info(f'Starting vLLM Tool Call Proxy on {args.host}:{args.port}')
    logger.info(f'Forwarding to: {VLLM_URL}')
    app.run(host=args.host, port=args.port, threaded=True)
