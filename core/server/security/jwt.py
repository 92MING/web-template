# -*- coding: utf-8 -*-

"""JWT infrastructure (RS256) for short-lived capability tokens.



Two scopes:

    - sub='file-upload' (FileUploadClaims): used by `/api/files/upload`.

    - sub='file-access' (FileAccessClaims): used by `/api/files/get|delete`.



Keys live in env vars JWT_PRIVATE_KEY / JWT_PUBLIC_KEY (PKCS8 PEM,

literal "\\n" escaped). `ensure_jwt_keys_or_warn` is invoked at server

startup to auto-generate the pair when both are missing.

"""



import os

import time

import uuid

import logging

import jwt



from functools import lru_cache

from pathlib import Path

from typing import Literal, TypedDict, NotRequired

from cryptography.hazmat.primitives import serialization

from cryptography.hazmat.primitives.asymmetric import rsa



JWT_ALG = 'RS256'

JWT_ISSUER = 'proj-template'



_logger = logging.getLogger(__name__)





class JwtError(Exception):

    '''Raised when JWT issuance or verification fails.'''





class FileUploadClaims(TypedDict):

    iss: Literal['proj-template']

    sub: Literal['file-upload']

    jti: str

    iat: int

    exp: int

    category: str

    max_size: int

    file_expire: float | None

    issuer_route: str

    allowed_mime_prefixes: NotRequired[list[str] | None]





class FileAccessClaims(TypedDict):

    iss: Literal['proj-template']

    sub: Literal['file-access']

    action: Literal['read', 'delete']

    jti: str

    iat: int

    exp: int

    category: str

    object_id: str





def _decode_pem_env(raw: str) -> str:

    return raw.replace('\\n', '\n')





@lru_cache(maxsize=1)

def get_private_key() -> str:

    raw = os.environ.get('JWT_PRIVATE_KEY')

    if not raw:

        raise JwtError('JWT_PRIVATE_KEY not set in env')

    return _decode_pem_env(raw)





@lru_cache(maxsize=1)

def get_public_key() -> str:

    raw = os.environ.get('JWT_PUBLIC_KEY')

    if not raw:

        raise JwtError('JWT_PUBLIC_KEY not set in env')

    return _decode_pem_env(raw)





def issue_upload_token(

    *,

    category: str,

    max_size: int,

    file_expire: float | None,

    issuer_route: str,

    allowed_mime_prefixes: list[str] | None = None,

    ttl: int = 300,

) -> str:

    '''Issue an upload-capability token for `/api/files/upload`.'''

    now = int(time.time())

    claims: FileUploadClaims = {

        'iss': JWT_ISSUER,

        'sub': 'file-upload',

        'jti': str(uuid.uuid4()),

        'iat': now,

        'exp': now + int(ttl),

        'category': category,

        'max_size': int(max_size),

        'file_expire': file_expire,

        'issuer_route': issuer_route,

    }

    if allowed_mime_prefixes is not None:

        claims['allowed_mime_prefixes'] = list(allowed_mime_prefixes)

    return jwt.encode(dict(claims), get_private_key(), algorithm=JWT_ALG)





def issue_access_token(

    *,

    category: str,

    object_id: str,

    action: Literal['read', 'delete'],

    ttl: int = 120,

) -> str:

    '''Issue a single-use access token for `/api/files/get|delete`.'''

    now = int(time.time())

    claims: FileAccessClaims = {

        'iss': JWT_ISSUER,

        'sub': 'file-access',

        'action': action,

        'jti': str(uuid.uuid4()),

        'iat': now,

        'exp': now + int(ttl),

        'category': category,

        'object_id': object_id,

    }

    return jwt.encode(dict(claims), get_private_key(), algorithm=JWT_ALG)





def verify_token(token: str, *, expected_sub: Literal['file-upload', 'file-access']) -> dict:

    '''Verify signature/exp/iss/sub. Raises JwtError on failure.'''

    try:

        decoded = jwt.decode(

            token,

            get_public_key(),

            algorithms=[JWT_ALG],

            issuer=JWT_ISSUER,

            options={'require': ['exp', 'iat', 'iss', 'sub', 'jti']},

        )

    except jwt.ExpiredSignatureError as exc:

        raise JwtError('token expired') from exc

    except jwt.InvalidTokenError as exc:

        raise JwtError(f'invalid token: {exc}') from exc

    if decoded.get('sub') != expected_sub:

        raise JwtError(f'token sub mismatch: expected {expected_sub}, got {decoded.get("sub")!r}')

    return decoded





def _generate_rsa_keypair() -> tuple[str, str]:

    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    public = private.public_key()

    priv_pem = private.private_bytes(

        encoding=serialization.Encoding.PEM,

        format=serialization.PrivateFormat.PKCS8,

        encryption_algorithm=serialization.NoEncryption(),

    ).decode('utf-8')

    pub_pem = public.public_bytes(

        encoding=serialization.Encoding.PEM,

        format=serialization.PublicFormat.SubjectPublicKeyInfo,

    ).decode('utf-8')

    return priv_pem, pub_pem





def _pem_to_env_literal(pem: str) -> str:

    return pem.replace('\n', '\\n')





def _upsert_env_file(env_path: Path, key: str, value: str) -> None:
    line = f'{key}="{value}"\n'
    if env_path.exists():
        existing = env_path.read_text(encoding='utf-8')
        lines = existing.splitlines(keepends=True)
        cleaned = [l for l in lines if not l.strip().startswith(f'{key}=')]
        if cleaned and not cleaned[-1].endswith('\n'):
            cleaned.append('\n')
        cleaned.append(line)
        env_path.write_text(''.join(cleaned), encoding='utf-8')
    else:
        env_path.write_text(line, encoding='utf-8')


def _read_key_from_env_file(env_path: Path, key: str) -> str | None:
    if not env_path.exists():
        return None
    for line in env_path.read_text(encoding='utf-8').splitlines():
        stripped = line.strip()
        if stripped.startswith(f'{key}='):
            value = stripped[len(key)+1:].strip().strip('"').strip("'")
            return value
    return None





def ensure_jwt_keys_or_warn(project_root: Path) -> None:
    '''Auto-generate JWT key pair when both env vars are missing.

    Behavior:
      - both missing in env → check .env file; if present, load into os.environ.
      - both missing in env and .env → generate, write to <project_root>/.env, set os.environ, warn.
      - one missing → log error and raise (half-configured state is unsafe).
      - both present → cache and return.
    '''
    priv = os.environ.get('JWT_PRIVATE_KEY')
    pub = os.environ.get('JWT_PUBLIC_KEY')
    env_path = project_root / '.env'

    if priv and pub:
        get_private_key.cache_clear()
        get_public_key.cache_clear()
        get_private_key()
        get_public_key()
        return

    if bool(priv) != bool(pub):
        _logger.error(
            'JWT_PRIVATE_KEY/JWT_PUBLIC_KEY are half-configured (priv=%s, pub=%s); '
            'refusing to start in this state.',
            bool(priv), bool(pub),
        )
        raise JwtError('JWT keys are half-configured: provide both or neither.')

    priv_from_file = _read_key_from_env_file(env_path, 'JWT_PRIVATE_KEY')
    pub_from_file = _read_key_from_env_file(env_path, 'JWT_PUBLIC_KEY')
    if priv_from_file and pub_from_file:
        os.environ['JWT_PRIVATE_KEY'] = priv_from_file
        os.environ['JWT_PUBLIC_KEY'] = pub_from_file
        get_private_key.cache_clear()
        get_public_key.cache_clear()
        get_private_key()
        get_public_key()
        _logger.info('JWT keys loaded from %s.', env_path)
        return

    if bool(priv_from_file) != bool(pub_from_file):
        _logger.error(
            'JWT_PRIVATE_KEY/JWT_PUBLIC_KEY are half-configured in %s (priv=%s, pub=%s); '
            'refusing to start in this state.',
            env_path, bool(priv_from_file), bool(pub_from_file),
        )
        raise JwtError('JWT keys are half-configured in .env: provide both or neither.')

    priv_pem, pub_pem = _generate_rsa_keypair()
    priv_env = _pem_to_env_literal(priv_pem)
    pub_env = _pem_to_env_literal(pub_pem)
    _upsert_env_file(env_path, 'JWT_PRIVATE_KEY', priv_env)
    _upsert_env_file(env_path, 'JWT_PUBLIC_KEY', pub_env)
    os.environ['JWT_PRIVATE_KEY'] = priv_env
    os.environ['JWT_PUBLIC_KEY'] = pub_env
    get_private_key.cache_clear()
    get_public_key.cache_clear()
    _logger.warning(
        'JWT_PUBLIC_KEY/JWT_PRIVATE_KEY not found in env or .env; generated RS256 2048-bit pair '
        'and wrote to %s. Restart not required.',
        env_path,
    )

