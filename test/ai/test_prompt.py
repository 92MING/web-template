

import json
import unittest

from core.ai.completion import Prompt, _json_schema_response_name
from core.utils.concurrent_utils import run_any_func
from core.utils.data_structs import PlainText


class _CustomLLMContent:
    def to_llm(self, **kwargs):
        return ['prefix', PlainText.Load(b'wrapped payload')]


class TestPromptAttachSerialization(unittest.TestCase):
    def test_prompt_roundtrip_preserves_native_str_and_file_attaches(self):
        prompt = Prompt(data='hello', attaches=['note', PlainText.Load(b'plain text')])

        restored = Prompt.model_validate_json(prompt.model_dump_json())

        self.assertEqual(restored.attaches[0], 'note')
        self.assertIsInstance(restored.attaches[1], PlainText)

    def test_prompt_roundtrip_wraps_custom_llm_content(self):
        prompt = Prompt(data='hello', attaches=[_CustomLLMContent()])

        dumped = json.loads(prompt.model_dump_json())
        self.assertIsInstance(dumped['attaches'][0], list)
        self.assertEqual(dumped['attaches'][0][0], 'prefix')

        restored = Prompt.model_validate_json(prompt.model_dump_json())
        unknown = restored.attaches[0]
        self.assertEqual(type(unknown).__name__, '_UnknownLLMContent')

        expanded = run_any_func(getattr(unknown, 'to_llm'))
        self.assertEqual(expanded[0], 'prefix')
        self.assertIsInstance(expanded[1], PlainText)


class TestJsonSchemaResponseName(unittest.TestCase):
    def test_prefers_schema_title(self):
        self.assertEqual(
            _json_schema_response_name({'title': 'My Response Schema'}),
            'My_Response_Schema',
        )

    def test_falls_back_when_title_missing(self):
        self.assertEqual(
            _json_schema_response_name({'type': 'object', 'properties': {}}),
            'response',
        )

    def test_prompt_validate_accepts_unknown_payload_list(self):
        payload = {
            'data': 'hello',
            'attaches': [['prefix', PlainText.Load(b'body').pydantic_dump()]],
        }

        prompt = Prompt.model_validate(payload)
        unknown = prompt.attaches[0]
        self.assertEqual(type(unknown).__name__, '_UnknownLLMContent')

        expanded = run_any_func(getattr(unknown, 'to_llm'))
        self.assertEqual(expanded[0], 'prefix')
        self.assertIsInstance(expanded[1], PlainText)


if __name__ == '__main__':
    unittest.main()