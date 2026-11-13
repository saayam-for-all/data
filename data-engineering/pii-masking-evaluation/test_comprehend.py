
from unittest.mock import Mock

from methods.comprehend_masking import mask_pii_with_comprehend

text = "My name is Priya Sharma and I need groceries."

name = "Priya Sharma"
start = text.index(name)

mock_client = Mock()
mock_client.detect_pii_entities.return_value = {
    "Entities": [
        {
            "Type": "NAME",
            "BeginOffset": start,
            "EndOffset": start + len(name),
            "Score": 0.99,
        }
    ]
}

result = mask_pii_with_comprehend(text, client=mock_client)

print("Original:", text)
print("Masked:  ", result)

assert "Priya Sharma" not in result
assert "[NAME]" in result
mock_client.detect_pii_entities.assert_called_once()

print("Mock Comprehend test passed!")
