"""
Which Claude model each kind of call uses. Change a tier here, or override it
per deployment with the env var, instead of editing every call site.

  MAIN    Anything a person reads as Oma's answer: the family-care and outreach
          agents, the answer about a photo, and answers from the knowledge base
          (insurance, medical tests, providers, emergency contacts), which go
          to the user as-is. Also the family-care router, which picks the tool
          for every message: a wrong pick (like re-sending a saved photo) is
          something the user sees. Quality comes before speed here.
  WORKER  Capable but quicker, for steps the user doesn't read directly:
          describing images for the record, composing emails, checking consent
          forms, the registration chat.
  FAST    Small, well-defined jobs where speed matters most: yes/no and label
          classifiers, pulling an age or name out of text, a country from a
          dialling code, shortening a long reply, one-line confirmations.

Every message passes through several of these in a row, so moving the helper
calls off MAIN is what makes replies noticeably quicker.
"""

import os

MAIN = os.getenv("OMA_MODEL_MAIN", "claude-opus-5-5")
WORKER = os.getenv("OMA_MODEL_WORKER", "claude-sonnet-5-5")
FAST = os.getenv("OMA_MODEL_FAST", "claude-haiku-5-5")
