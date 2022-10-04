from samtranslator.metrics.method_decorator import cw_timer
from samtranslator.plugins import BasePlugin
from samtranslator.swagger.swagger import SwaggerEditor
from samtranslator.open_api.open_api import OpenApiEditor
from samtranslator.public.sdk.resource import SamResourceType
from samtranslator.public.sdk.template import SamTemplate
import json
from samtranslator.utils.py27hash_fix import Py27Dict
from samtranslator.intrinsics.resolver import IntrinsicsResolver
from samtranslator.intrinsics.actions import RefAction


class DefaultDefinitionBodyPlugin(BasePlugin):
    """
    If the user provides no DefinitionBody or DefinitionUri, we will generate a default DefinitionBody
    If the user provides a DefinitionBody and sets MergeGeneratedSwaggerWithDefinitionBody to true, we will merge the generated
    DefinitionBody with the user provided DefinitionBody
    """

    def __init__(self):
        """
        Initialize the plugin.
        """
        self.backup = {}
        super(DefaultDefinitionBodyPlugin, self).__init__(DefaultDefinitionBodyPlugin.__name__)

    @cw_timer(prefix="Plugin-APIOverridesWithBody")
    def on_before_transform_template(self, template_dict):
        """
        Hook method that gets called before the SAM template is processed.
        The template has passed the validation and is guaranteed to contain a non-empty "Resources" section.

        :param dict template_dict: Dictionary of the SAM template
        :return: Nothing
        """
        template = SamTemplate(template_dict)

        for api_type in [SamResourceType.Api.value, SamResourceType.HttpApi.value]:
            for logicalId, api in template.iterate({api_type}):
                if api.properties.get("DefinitionUri"):
                    continue

                if api.properties.get("DefinitionBody") and api.properties.get("MergeGeneratedSwaggerWithDefinitionBody") is True:
                    # This sucks, but literally all of the other helper functions in Py27Dict mangle the dict
                    self.backup[unUnicode(logicalId)] = unUnicode(api.properties.get("DefinitionBody"))
                    api.properties.pop("DefinitionBody")
                elif api.properties.get("DefinitionBody"):
                    continue

                if api_type is SamResourceType.HttpApi.value:
                    # If "Properties" is not set in the template, set them here
                    if not api.properties:
                        template.set(logicalId, api)
                    api.properties["DefinitionBody"] = OpenApiEditor.gen_skeleton()

                if api_type is SamResourceType.Api.value:
                    api.properties["DefinitionBody"] = SwaggerEditor.gen_skeleton()

                api.properties["__MANAGE_SWAGGER"] = True

        #Handle overriding the DefinitionBody with path overrides in function definitions
        for logicalId, function in template.iterate({SamResourceType.Function.value}):
            for event in function.properties.get("Events").values() if "Events" in function.properties else []:
                if "Properties" in event.keys() and "SchemaOverridesAtPath" in event["Properties"].keys():

                    resolver = IntrinsicsResolver(template.resources, {RefAction.intrinsic_name: RefAction()})
                    api = resolver.resolve_parameter_refs(event["Properties"]["RestApiId"])
                    if not api:
                        continue
                    apiId = unUnicode(event["Properties"]["RestApiId"].values()[0])
                    override_template = {
                        "paths": {
                            unUnicode(event["Properties"]["Path"]): unUnicode(
                                event["Properties"]["SchemaOverridesAtPath"])
                        }
                    }
                    if self.backup[apiId]:
                        self.backup[apiId] = merge(unUnicode(self.backup[apiId]), override_template)
                    else:
                        self.backup[apiId] = override_template
                        
        print("done")

    def on_after_transform_template(self, template_dict):
        # Handle overriding the Swagger generated DefinitionBody with the user provided DefinitionBody
        #  inside API definitions
        template = SamTemplate(template_dict)
        for key in self.backup:
            backup = unUnicode(self.backup[key])
            api = template.get(key)
            body = unUnicode(api.properties.get("Body"))
            merged = merge(body, backup)
            api.properties["Body"].update(merged)
            template.set(key, api)

def unUnicode(s):
    if (type(s) == str):
        return s.encode('ascii')
    else:
        return json.loads(json.dumps(s).encode('ascii'))

def merge(a, b, path=None):
    "merges b into a"
    if path is None:
        path = []
    for key in b.keys():
        if key in a.keys() and key in b.keys():
            if isinstance(a[key], dict) and isinstance(b[key], dict):
                #print("Both sides are dicts")
                merge(a[key], b[key], path + [str(key)])
            elif isinstance(a[key], list) and isinstance(b[key], list):
                #print("Both sides are lists")
                a[key] = a[key] + b[key]
            elif a[key] == b[key]:
                #print("Both sides are equal")
                pass
            elif type(a[key]) != type(b[key]):
                print("WARN: Type of %s is %s, not %s" % (path + [str(key)], type(a[key]), type(b[key])))
                a[key] = b[key]
            else:
                # b always trumps a
                print("WARN: No merge strategy for %s of type %s vs type %s" % (path + [str(key)], type(a[key]), type(b[key])))
                a[key] = b[key]
        else:
            a[key] = b[key]
    return a
