"""
PostgreSQL Semantic MCP Server

Um servidor MCP que fornece interface semântica inteligente
para bancos de dados PostgreSQL.

Funcionalidades:
- Descoberta automática do schema
- Mapeamento semântico de termos
- Tools de alto nível orientadas a intenção
- Resources para contexto e diretrizes
- Prompts reutilizáveis
- Suporte opcional a RAG

Uso:
    python server.py

Variáveis de ambiente:
    POSTGRES_DSN - Connection string (legacy)
    POSTGRES_DB_1_NAME, POSTGRES_DB_1_DSN - Multi-database mode
"""

import logging
import sys
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from app.prompts import register_prompts
from app.resources import (
    register_example_resources,
    register_guideline_resources,
    register_schema_resources,
)
from app.semantic_tools import register_semantic_tools
from app.services.discovery import discovery_service
from app.services.rag import rag_service
from app.services.semantic_mapper import semantic_mapper
from core.connection import close_pools, initialize_pools
from tools.query import register_query_tools
from tools.schema import register_schema_tools

load_dotenv()

# Configuração de logs vai para stderr (stdout é reservado para MCP)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("postgresql_mcp")


@asynccontextmanager
async def lifespan(app):
    """
    Lifecycle do servidor MCP.

    Inicializa pools de conexão, descobre schemas e
    prepara serviços de mapeamento semântico.
    """
    logger.info("=" * 60)
    logger.info("Starting PostgreSQL Semantic MCP Server...")
    logger.info("=" * 60)

    # Inicializa pools de conexão
    await initialize_pools()
    logger.info("Connection pools initialized")

    # Descobre schemas de todos os bancos
    try:
        db_maps = await discovery_service.discover_all()
        logger.info(f"Discovered {len(db_maps)} database(s)")

        # Registra schemas no mapeador semântico
        for alias, db_map in db_maps.items():
            logger.info(f"Registering semantic mapper for: {alias}")
            semantic_mapper.register_database_schema(db_map)

            # Indexa para RAG se disponível
            if await rag_service.initialize():
                logger.info(f"Indexing schema for RAG: {alias}")
                rag_service.index_schema(db_map)

    except Exception as e:
        logger.error(f"Schema discovery failed: {e}")
        # Continua mesmo sem descoberta para permitir reconexão

    logger.info("MCP Server ready!")
    logger.info("=" * 60)

    yield

    # Shutdown
    logger.info("Shutting down MCP Server...")
    await close_pools()
    logger.info("MCP Server stopped")


# Cria instância FastMCP
mcp = FastMCP("postgresql_semantic_mcp", lifespan=lifespan)

# Registra tools existentes (baixo nível)
register_query_tools(mcp)
register_schema_tools(mcp)

# Registra novas tools semânticas (alto nível)
register_semantic_tools(mcp)

# Registra resources
register_guideline_resources(mcp)
register_schema_resources(mcp)
register_example_resources(mcp)

# Registra prompts
register_prompts(mcp)

if __name__ == "__main__":
    # Executa via stdio (protocolo MCP)
    mcp.run()
