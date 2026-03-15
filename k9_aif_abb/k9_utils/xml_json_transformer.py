# SPDX-License-Identifier: MIT
# (c) 2025 Ravi Natarajan. All rights reserved.

"""
XML <-> JSON Data Transformers
----------------------------
Out-of-Box (OOB) data transformers implementing bidirectional conversion
between XML and JSON formats under the K9-AIF DataTransformationFactory ABB.

Classes:
    - JsonToXmlDataTransformer  ->  JSON -> XML
    - XmlToJsonDataTransformer  ->  XML -> JSON
"""

import json
import xmltodict
import dicttoxml
from k9_factories.data_transformation_factory import BaseDataTransformer


# ##
# #                       JSON -> XML Transformer (OOB)                        #
# ##
class JsonToXmlDataTransformer(BaseDataTransformer):
    """Concrete SBB: Converts JSON to XML format."""

    def transform(self, data, **kwargs):
        self.log_trace("Starting JSON->XML transformation.")
        try:
            xml_bytes = dicttoxml.dicttoxml(data, attr_type=False, custom_root="root")
            xml_str = xml_bytes.decode("utf-8")

            if not xml_str.strip():
                raise ValueError("Empty XML transformation output")

            self.log_trace(f"Transformation complete. Output size: {len(xml_str)} chars.")
            return xml_str

        except Exception as ex:
            self.log_trace(f"Error during JSON->XML transformation: {ex}")
            raise

    def validate(self, data):
        """Basic validation: XML output must begin with <."""
        valid = isinstance(data, str) and data.strip().startswith("<")
        if not valid:
            self.log_trace("Validation failed: Invalid XML output.")
        return valid


# ##
# #                       XML -> JSON Transformer (OOB)                        #
# ##
class XmlToJsonDataTransformer(BaseDataTransformer):
    """Concrete SBB: Converts XML to JSON format."""

    def transform(self, xml_input: str, **kwargs):
        self.log_trace("Starting XML->JSON transformation.")

        try:
            parsed = xmltodict.parse(xml_input)
            json_data = json.loads(json.dumps(parsed))

            if not isinstance(json_data, dict):
                raise ValueError("Parsed JSON is not a dictionary")

            self.log_trace(f"Transformation complete. Keys: {len(json_data.keys())}")
            return json_data

        except Exception as ex:
            self.log_trace(f"Error during XML->JSON transformation: {ex}")
            raise

    def validate(self, data):
        """Basic validation: must be a dict with non-zero keys."""
        valid = isinstance(data, dict) and bool(data)
        if not valid:
            self.log_trace("Validation failed: Empty or invalid JSON data.")
        return valid