import json
import unittest

from probe import IDENTIFIER, validate_tool_response


def response(value, name="lookup_order"):
    return {
        "choices": [
            {
                "message": {
                    "tool_calls": [
                        {
                            "type": "function",
                            "function": {
                                "name": name,
                                "arguments": json.dumps({"order_id": value}),
                            },
                        }
                    ]
                }
            }
        ]
    }


class ParserAcceptanceTests(unittest.TestCase):
    def test_preserves_numeric_string(self):
        validate_tool_response(response(IDENTIFIER))

    def test_rejects_integer_coercion(self):
        with self.assertRaises(ValueError):
            validate_tool_response(response(int(IDENTIFIER)))

    def test_rejects_lost_leading_zeros(self):
        with self.assertRaises(ValueError):
            validate_tool_response(response(str(int(IDENTIFIER))))

    def test_rejects_wrong_tool(self):
        with self.assertRaises(ValueError):
            validate_tool_response(response(IDENTIFIER, "send_email"))

    def test_rejects_missing_tool(self):
        with self.assertRaises(ValueError):
            validate_tool_response({"choices": [{"message": {"content": "done"}}]})


if __name__ == "__main__":
    unittest.main()
