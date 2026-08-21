from src.games.manager import GameManager
from src.games.plugins.text_based.chameleon import ChameleonGame
from src.games.plugins.text_based.mafia import MafiaGame
from src.utils.logger import get_logger

logger = get_logger(__name__)

# Only games whose gameplay is implemented in this repository are registered.
_LOCAL_GAME_CLASSES = {
    "mafia": MafiaGame,
    "chameleon": ChameleonGame,
}


def register_game_features(app) -> None:
    """Register bot-owned games; external web apps are intentionally excluded."""
    del app  # Kept in the public registration contract used by feature loading.
    for name, game_class in _LOCAL_GAME_CLASSES.items():
        try:
            GameManager.register_game(name, game_class)
            logger.info("game_registered", game=name, owner="guardian_bot")
        except ValueError:
            # Registration can be called more than once during tests/startup reloads.
            if GameManager.get_game_class(name) is not game_class:
                raise
            logger.debug("game_already_registered", game=name)
        except Exception as exc:
            logger.exception(
                "game_register_failed",
                game=name,
                error=type(exc).__name__,
            )

    logger.info(
        "all_games_registered",
        total_games=len(GameManager.list_games()),
        games=list(_LOCAL_GAME_CLASSES),
        owner="guardian_bot",
    )


_FEATURE_MODULES: dict[str, bool] = {
    "azkar": True,
    "instagram": True,
    "media_downloader": True,
    "quotes": True,
    "quran": True,
    "smart_detect": True,
    "soundcloud": True,
    "voice_chat": True,
}


def register_all_features(app) -> None:
    """Register available optional feature modules without importing missing modules."""
    from importlib import import_module

    registered: list[str] = []
    failed: list[str] = []
    for feature_name, enabled in _FEATURE_MODULES.items():
        if not enabled:
            continue
        try:
            module = import_module(f"src.features.{feature_name}")
            register_handlers = module.register_handlers
            register_handlers(app)
            registered.append(feature_name)
        except (ImportError, AttributeError) as exc:
            failed.append(feature_name)
            logger.warning(
                "optional_feature_unavailable",
                feature=feature_name,
                error=type(exc).__name__,
            )
        except Exception as exc:
            failed.append(feature_name)
            logger.exception(
                "feature_register_failed",
                feature=feature_name,
                error=type(exc).__name__,
            )

    logger.info(
        "all_features_registered",
        registered=registered,
        unavailable=failed,
    )
    register_game_features(app)
