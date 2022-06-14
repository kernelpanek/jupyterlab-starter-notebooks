import configparser
import html
from pathlib import Path
from pprint import pformat
from urllib.parse import urlparse

import boto3
import botocore.model
import botocore.utils
from IPython.core.display import HTML
from jinja2 import Environment, FileSystemLoader
from pygments import highlight
from pygments.formatters import Terminal256Formatter
from pygments.lexers import PythonLexer

AWS_US_REGIONS = ["us-east-1", "us-east-2", "us-west-1", "us-west-2"]
AWS_CA_REGIONS = ["ca-central-1"]
AWS_SA_REGIONS = ["sa-east-1"]
AWS_EU_REGIONS = ["eu-west-3", "eu-west-2", "eu-west-1", "eu-central-1"]
AWS_ASIA_REGIONS = [
    "ap-south-1",
    "ap-northeast-2",
    "ap-northeast-1",
    "ap-southeast-1",
    "ap-southeast-2",
]
AWS_ALL_REGIONS = (
    AWS_US_REGIONS
    + AWS_CA_REGIONS
    + AWS_SA_REGIONS
    + AWS_EU_REGIONS
    + AWS_ASIA_REGIONS
)

AWS_SERVICES_CONDENSED = [
    "cloudfront",
    "cloudtrail",
    "ec2",
    "s3",
    "elb",
    "iam",
    "rds",
    "route53",
    "route53domains",
    "sns",
    "sqs",
    "sts",
]
AWS_SERVICES_DATA = [
    "athena",
    "rds",
    "dynamodb",
    "elasticache",
    "redshift",
    "neptune",
    "dms",
]
AWS_SERVICES_COMPUTE = ["ec2", "lambda", "stepfunctions"]
AWS_SERVICES_OPS = ["cloudformation", "opsworks", "opsworkscm", "ssm"]
AWS_SERVICES_MGMT = [
    "cloudtrail",
    "cloudwatch",
    "budgets",
    "config",
    "cur",
    "events",
    "iam",
    "logs",
    "organizations",
    "pricing",
    "servicecatalog",
    "ssm",
    "sts",
]


def list_profile_names(profile_exclusions=[], keyword_exclusions=[]):
    config = configparser.ConfigParser()
    config.read(Path("~/", ".aws", "config").expanduser())
    profile_names = [
        section.replace("profile ", "") for section in config.sections()
    ]
    exclude = profile_exclusions + [
        x for x in profile_names for kw in keyword_exclusions if kw in x
    ]
    profile_list = [x for x in profile_names if x not in exclude]
    return profile_list


def list_regions():
    sess = boto3.session.Session(profile_name=list_profile_names()[0])
    ec2 = sess.client("ec2", "us-east-1")
    regions = ec2.describe_regions().get("Regions")
    return [region.get("RegionName") for region in regions]


def list_services_for_region(region):
    sess = boto3.session.Session(
        profile_name=list_profile_names()[0], region_name=region
    )
    return sess.get_available_services()


def pprint_color(obj):
    print(highlight(pformat(obj), PythonLexer(), Terminal256Formatter()))


def render_template(template_file, **kwargs):
    templateLoader = FileSystemLoader(searchpath="./")
    templateEnv = Environment(loader=templateLoader)

    template = templateEnv.get_template(template_file)
    outputText = template.render(**kwargs)
    return outputText


def get_shape_data(client, shape_for):
    shape = client.meta.service_model.shape_for(shape_for)
    shape_return = {
        botocore.model.StringShape: lambda x: dict(
            enum=x.enum, docs=x.documentation
        ),
        botocore.model.StructureShape: lambda x: dict(
            name=x.name,
            required=x.required_members,
            members={
                k: get_shape_data(client, v.name) for k, v in x.members.items()
            },
            docs=x.documentation,
        ),
        botocore.model.ListShape: lambda x: get_shape_data(
            client, x.member.name
        ),
        botocore.model.MapShape: lambda x: dict(
            type=str(type(x)), name=x.name
        ),
        botocore.model.Shape: lambda x: dict(type=x.name),
    }
    return shape_return.get(type(shape), lambda x: dict())(shape)


def generate_cloudtrail_reference(region="us-east-1", svc_include=None):
    """
    Generates a dictionary object containing a quick reference of event sources
    and event function names for every AWS service or only the services included
    in `svc_include`.
    """
    if svc_include is None:
        svc_include = []
    session = boto3.session.Session(region_name=region)
    services = session.get_available_services()

    if len(svc_include) > 0:
        services = {
            svc_name: session.client(svc_name)
            for svc_name in services
            if svc_name in svc_include
        }
    else:
        services = {
            svc_name: session.client(svc_name)
            for svc_name in services
        }
    data = {
        svc_name: dict(
            EventSource=urlparse(client.meta.endpoint_url).netloc.replace(
                f"{region}.", ""
            ),
            EventNames=client.meta.service_model.operation_names,
        )
        for svc_name, client in services.items()
    }
    return data


def generate_json_input_for(method):
    client = method.__self__
    method_name = client.meta.method_to_api_mapping[method.__func__.__name__]
    arg_gen = botocore.utils.ArgumentGenerator()
    input_model = arg_gen.generate_skeleton(
        client.meta.service_model.operation_model(method_name).input_shape
    )
    return input_model


def generate_html_for(method, param_name=None):
    page_src = ""
    client = method.__self__
    method_name = client.meta.method_to_api_mapping[method.__func__.__name__]
    if param_name is None:
        for key, val in client.meta.service_model.operation_model(
            method_name
        ).input_shape.members.items():
            docs = (
                client.meta.service_model.operation_model(method_name)
                .input_shape.members[key]
                .documentation
            )
            page_src += "<h3>{0}</h3><h4>{1}</h4>".format(
                key, html.escape(str(val))
            )
            page_src += "<div>"
            if len(docs) > 0:
                page_src += docs
            page_src += "<pre>{}</pre>".format(
                json.dumps(
                    get_shape_data(client, val.name), indent=2, sort_keys=True
                )
            )
            page_src += "<div>"
    else:
        param = client.meta.service_model.operation_model(
            method_name
        ).input_shape.members[param_name]
        docs = param.documentation
        page_src += "<h3>{0}</h3><h4>{1}</h4>".format(
            param_name, html.escape(str(param))
        )
        page_src += "<div>"
        if len(docs) > 0:
            page_src += docs
        page_src += "<pre>{}</pre>".format(
            json.dumps(
                get_shape_data(client, param.name), indent=2, sort_keys=True
            )
        )
        page_src += "<div>"
    return HTML(page_src)
