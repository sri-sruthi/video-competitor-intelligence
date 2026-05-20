from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class FakeGeminiResponse:
    def __init__(self, text: str) -> None:
        self.text = text


class FakeGenerateContentConfig:
    def __init__(self, *, system_instruction: str) -> None:
        self.system_instruction = system_instruction


class FakeModelsAPI:
    def __init__(self, owner: "FakeClient") -> None:
        self.owner = owner

    def _record_and_resolve(self, *, model: str, contents: str, config) -> FakeGeminiResponse:
        self.owner.calls.append(
            {
                "model": model,
                "contents": contents,
                "config": config,
            }
        )

        if FakeClient.queued_results:
            result = FakeClient.queued_results.pop(0)
        else:
            result = ""

        if isinstance(result, Exception):
            raise result

        return FakeGeminiResponse(str(result))

    async def generate_content(
        self, *, model: str, contents: str, config
    ) -> FakeGeminiResponse:
        return self._record_and_resolve(
            model=model,
            contents=contents,
            config=config,
        )


class FakeSyncModelsAPI(FakeModelsAPI):
    def generate_content(self, *, model: str, contents: str, config) -> FakeGeminiResponse:
        return self._record_and_resolve(
            model=model,
            contents=contents,
            config=config,
        )


class FakeAsyncClient:
    def __init__(self, owner: "FakeClient") -> None:
        self.models = FakeModelsAPI(owner)


class FakeClient:
    created_clients: list["FakeClient"] = []
    queued_results: list[object] = []

    def __init__(self, *, api_key: str) -> None:
        self.api_key = api_key
        self.calls: list[dict] = []
        self.models = FakeSyncModelsAPI(self)
        self.aio = FakeAsyncClient(self)
        self.__class__.created_clients.append(self)

    @classmethod
    def reset(cls) -> None:
        cls.created_clients = []
        cls.queued_results = []


class FakeTrendReq:
    created_instances: list["FakeTrendReq"] = []

    def __init__(self, *args, **kwargs) -> None:
        self.args = args
        self.kwargs = kwargs
        self.df = None
        self.raise_on_build = None
        self.last_payload = None
        self.__class__.created_instances.append(self)

    def build_payload(self, **kwargs) -> None:
        self.last_payload = kwargs
        if self.raise_on_build is not None:
            raise self.raise_on_build

    def interest_over_time(self):
        return self.df

    @classmethod
    def reset(cls) -> None:
        cls.created_instances = []


def load_ai_module():
    FakeClient.reset()

    fake_genai_pkg = types.ModuleType("google.genai")
    fake_genai_pkg.Client = FakeClient

    fake_genai_types = types.ModuleType("google.genai.types")
    fake_genai_types.GenerateContentConfig = FakeGenerateContentConfig

    fake_google = types.ModuleType("google")
    fake_google.genai = fake_genai_pkg

    sys.modules.pop("backend.services.ai_service", None)
    with patch.dict(
        sys.modules,
        {
            "google": fake_google,
            "google.genai": fake_genai_pkg,
            "google.genai.types": fake_genai_types,
        },
    ):
        module = importlib.import_module("backend.services.ai_service")

    return module, FakeClient


def load_seo_module():
    FakeTrendReq.reset()

    fake_request = types.ModuleType("pytrends.request")
    fake_request.TrendReq = FakeTrendReq

    fake_pytrends = types.ModuleType("pytrends")
    fake_pytrends.request = fake_request

    sys.modules.pop("backend.services.seo_service", None)
    with patch.dict(
        sys.modules,
        {
            "pytrends": fake_pytrends,
            "pytrends.request": fake_request,
        },
    ):
        module = importlib.import_module("backend.services.seo_service")

    return module, FakeTrendReq
