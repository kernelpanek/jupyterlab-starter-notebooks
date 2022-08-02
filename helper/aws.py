import asyncio
import json
from collections import defaultdict
from collections.abc import MutableMapping
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime

import boto3
import botocore

json.JSONEncoder.default = lambda self, obj: (
    obj.isoformat() if isinstance(obj, datetime) or isinstance(obj, date) else None
)


class NamifiedConnection(MutableMapping):
    def __init__(self, obj):
        """
        Take obj as dict and rename any keys
        """
        self.__dict__ = {
            NamifiedConnection.sanitize_name(k): NamifiedConnection(v) if isinstance(v, dict) else v
            for k, v in dict(obj).items()
        }

    def __setitem__(self, key, value):
        self.__dict__[key.replace("-", "_")] = value

    def __getitem__(self, key):
        return self.__dict__[key.replace("-", "_")]

    def __delitem__(self, key):
        del self.__dict__[key.replace("-", "_")]

    def __iter__(self):
        return iter(self.__dict__)

    def __len__(self):
        return len(self.__dict__)

    def __str__(self):
        """returns simple dict representation of the mapping"""
        return str(self.__dict__)

    def __repr__(self):
        """echoes class, id, & reproducible representation in the REPL"""
        return "{}, NamifiedConnection({})".format(
            super(NamifiedConnection, self).__repr__(), self.__dict__
        )

    def sanitize_name(name):
        keywords = [
            "False",
            "class",
            "finally",
            "is",
            "return",
            "None",
            "continue",
            "for",
            "lambda",
            "try",
            "True",
            "def",
            "from",
            "nonlocal",
            "while",
            "and",
            "del",
            "global",
            "not",
            "with",
            "as",
            "elif",
            "if",
            "or",
            "yield",
            "assert",
            "else",
            "import",
            "pass",
            "break",
            "except",
            "in",
            "raise",
        ]
        if name in keywords:
            name = f"_{name}"
        name = name.replace("-", "_")
        return name


def retrieve_all_pages(client, method, *args, **kwargs):
    try:
        pager = client.get_paginator(method)
        results = pager.paginate(*args, **kwargs).build_full_result()
    except:
        client_fuction = getattr(client, method)
        results = client_fuction(*args, **kwargs)
    results_clean = {k: v for k, v in results.items() if k != "ResponseMetadata"}
    return results_clean


def perform_aws_operations(aws_ctx_obj, callable_func):
    aws_data = defaultdict(lambda: defaultdict(dict))
    acct_regions = [
        (acct, region)
        for acct, reg_ctx in aws_ctx_obj.items()
        for region, ctx in reg_ctx.items()
    ]
    with ThreadPoolExecutor(max_workers=len(acct_regions)) as mpe:
        future_work = {
            mpe.submit(callable_func, aws_ctx_obj, acct, region): (acct, region)
            for acct, reg_ctx in aws_ctx_obj.items()
            for region, ctx in reg_ctx.items()
        }
        for future in as_completed(future_work):
            acct_region = future_work[future]
            data = future.result()
            aws_data[acct_region[0]][acct_region[1]] = data
    return aws_data


async def get_session_client(session, service, config=None):
    if not config:
        config = botocore.config.Config(
            read_timeout=180,
            connect_timeout=20,
            retries={"max_attempts": 2}
        )
    session_client = session.client(service)
    return service, session_client


async def make_all_connections(
    profiles=None,
    regions=None,
    svc_include=None,
    svc_exclude=None,
    connection_config=None,
):
    if svc_exclude is None:
        svc_exclude = []
    if svc_include is None:
        svc_include = []
    if regions is None:
        regions = []
    if profiles is None:
        profiles = []
    account_connections = {}
    for profile in profiles:
        account_connections.update({profile: {}})
        for region in regions:
            sess = boto3.session.Session(
                profile_name=profile, region_name=region
            )
            account_connections[profile].update({region: {}})
            connections = {}
            services = sess.get_available_services()
            if len(svc_include) > 0:
                services = [svc for svc in services if svc in svc_include]
            elif len(svc_exclude) > 0:
                services = [svc for svc in services if svc not in svc_exclude]
            deferred_sessions = (
                get_session_client(sess, service, connection_config) for service in services
            )
            gathered_sessions = await asyncio.gather(
                *deferred_sessions, return_exceptions=True
            )
            for service, session_client in gathered_sessions:
                connections[service] = session_client

            account_connections[profile][region] = connections
    account_connections = NamifiedConnection(account_connections)
    return account_connections


async def aws_connect(
    profiles=None,
    regions=None,
    svc_include=None,
    svc_exclude=None,
    connection_config=None,
):
    if svc_exclude is None:
        svc_exclude = []
    if svc_include is None:
        svc_include = []
    if regions is None:
        regions = []
    if profiles is None:
        profiles = []
    aws_conn = await make_all_connections(
        profiles=profiles,
        regions=regions,
        svc_include=svc_include,
        svc_exclude=svc_exclude,
        connection_config=connection_config,
    )

    return aws_conn
