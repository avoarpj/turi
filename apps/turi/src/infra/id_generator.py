from apps.turi.src.config.projectsettings import settings
from snowflake import SnowflakeGenerator

idgen = SnowflakeGenerator(
    instance=settings.SNOWFLAKE_INSTACE_ID,
    epoch=settings.SNOWFLAKE_EPOCH
)