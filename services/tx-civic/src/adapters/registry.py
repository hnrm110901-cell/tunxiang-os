"""适配器注册表 + 自动发现。

提供三级查找策略:
1. 精确匹配 city_code (如 "310100" 上海浦东)
2. 省级回退 city_code[:2] + "0000" (如 "310000" 上海)
3. 通用兜底 "000000" (GenericAdapter)
"""

import importlib
import pkgutil
from pathlib import Path
from typing import Any

import structlog

from .base_city_adapter import BaseCityAdapter

logger = structlog.get_logger(__name__)


class CityAdapterRegistry:
    """城市适配器注册表。"""

    _adapters: dict[str, type[BaseCityAdapter]] = {}

    @classmethod
    def register(cls, city_code: str):
        """装饰器 — 注册城市适配器。

        用法::

            @CityAdapterRegistry.register("310000")
            class ShanghaiCityAdapter(BaseCityAdapter):
                ...
        """

        def decorator(adapter_cls: type[BaseCityAdapter]) -> type[BaseCityAdapter]:
            if city_code in cls._adapters:
                logger.warning(
                    "city_adapter_overwrite",
                    city_code=city_code,
                    old=cls._adapters[city_code].__name__,
                    new=adapter_cls.__name__,
                )
            cls._adapters[city_code] = adapter_cls
            logger.debug(
                "city_adapter_registered",
                city_code=city_code,
                adapter=adapter_cls.__name__,
            )
            return adapter_cls

        return decorator

    @classmethod
    def get_adapter(cls, city_code: str, config: dict[str, Any]) -> BaseCityAdapter:
        """获取城市适配器实例（三级查找）。

        1. 精确匹配 city_code
        2. 省级回退 city_code[:2] + "0000"
        3. 通用兜底 "000000"
        """
        # 确保已执行自动发现
        if not cls._adapters:
            cls._auto_discover()

        # 1) 精确匹配
        adapter_cls = cls._adapters.get(city_code)

        # 2) 省级回退
        if adapter_cls is None:
            province_code = city_code[:2] + "0000"
            adapter_cls = cls._adapters.get(province_code)
            if adapter_cls is not None:
                logger.info(
                    "city_adapter_province_fallback",
                    requested=city_code,
                    resolved=province_code,
                )

        # 3) 通用兜底
        if adapter_cls is None:
            adapter_cls = cls._adapters.get("000000")
            if adapter_cls is not None:
                logger.info(
                    "city_adapter_generic_fallback",
                    requested=city_code,
                )

        if adapter_cls is None:
            raise ValueError(f"未找到城市适配器: city_code={city_code}，且无通用兜底适配器(000000)")

        return adapter_cls(city_code=city_code, config=config)

    @classmethod
    def list_supported_cities(cls) -> dict[str, str]:
        """返回所有已注册的城市代码及其适配器类名。"""
        if not cls._adapters:
            cls._auto_discover()
        return {code: adapter.__name__ for code, adapter in cls._adapters.items()}

    @classmethod
    def _auto_discover(cls) -> None:
        """自动导入 adapters 下所有子目录的适配器模块。

        扫描 adapters/ 下的子包，导入其中所有模块，
        触发 @CityAdapterRegistry.register 装饰器完成注册。
        """
        adapters_dir = Path(__file__).parent

        for pkg_info in pkgutil.iter_modules([str(adapters_dir)]):
            if not pkg_info.ispkg:
                continue

            pkg_path = adapters_dir / pkg_info.name
            pkg_module_name = f"{__package__}.{pkg_info.name}"

            try:
                importlib.import_module(pkg_module_name)
            except ImportError as e:
                logger.warning(
                    "city_adapter_pkg_import_failed",
                    package=pkg_info.name,
                    error=str(e),
                )
                continue

            # 导入子包内所有模块
            for mod_info in pkgutil.iter_modules([str(pkg_path)]):
                mod_name = f"{pkg_module_name}.{mod_info.name}"
                try:
                    importlib.import_module(mod_name)
                except ImportError as e:
                    logger.warning(
                        "city_adapter_module_import_failed",
                        module=mod_name,
                        error=str(e),
                    )

        logger.info(
            "city_adapter_discovery_complete",
            registered_count=len(cls._adapters),
            city_codes=list(cls._adapters.keys()),
        )
