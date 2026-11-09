import logging

from downloaders.tse import (
    tse_candidatures_photos,
    tse_candidates_downloader,
    tse_evm_bulletins_downloader,
    tse_municipalities_downloader,
    tse_political_parties_directory_downloader,
)
from downloaders.camaradosdeputados import cd_federal_deputies, cd_legislatures, cd_ceaps
from downloaders.sds import sds_federal_deputies_history, sds_municipalities_centroid, sds_federal_deputies_detailed
from downloaders.gov import gov_amendments, gov_municipalities
from downloaders.receitafederal import receitafederal_cnaes, receitafederal_empresas, receitafederal_estabelecimentos, receitafederal_socios
from downloaders.ibge import ibge_enderecos
from downloaders.tse_voting_locations import tse_voting_locations_downloader

logger = logging.getLogger(__name__)

class OpendataDownloadsEntrypoint:    
    def run(self) -> None:
        # Tribunal Superior Eleitoral (TSE)
        logger.info("Downloading voting locations from TSE")
        _, errors = tse_voting_locations_downloader.get_meta_files_or_download(
            "zip", "application/zip"
        )
        if errors:
            raise RuntimeError(f"Falha em {len(errors)} downloads de locais de votação")

        logger.info("Downloading municipalities from TSE")
        #tse_municipalities_downloader.get_meta_files_or_download("zip", "application/zip")
        logger.info("end\n\n")

        logger.info("Downloading evm bulletins from TSE")
        _, errors = tse_evm_bulletins_downloader.get_meta_files_or_download(
            "zip", "application/zip"
        )
        if errors:
            raise RuntimeError(f"Falha em {len(errors)} downloads de boletins de urna")

        logger.info("end\n\n")

        logger.info("Downloading candidates from TSE")
        _, errors = tse_candidates_downloader.get_meta_files_or_download(
            "zip", "application/zip"
        )
        if errors:
            raise RuntimeError(f"Falha em {len(errors)} downloads de candidaturas")

        logger.info("end\n\n")

        logger.info("Downloading candidate photos from TSE")
        #tse_candidatures_photos.get_meta_files_or_download("zip", "application/zip")
        logger.info("end\n\n")

        logger.info("Downloading political parties directories from TSE")
        #tse_political_parties_directory_downloader.get_meta_files_or_download("zip", "application/zip")
        logger.info("end\n\n")

        '''logger.info("Downloading tse candidatures photos")
        _, errors = tse_candidatures_photos.get_meta_files_or_download(
            "zip", "application/zip"
        )
        if errors:
            for error in errors[:5]:
                logger.error("Candidate photo download failed: %s: %s", error.path, error)

            raise RuntimeError(f"Falha em {len(errors)} downloads de fotos do TSE")

        logger.info("end\n\n")
        '''

        # Câmara dos Deputados (CD)
        logger.info("Downloading federal deputies list from câmara dos deputados")
        cd_federal_deputies.get_meta_files_or_download("json", "application/json")
        logger.info("end\n\n")

        logger.info("Downloading legislatures from câmara dos deputados")
        cd_legislatures.get_meta_files_or_download("json", "application/json")
        logger.info("end\n\n")

        # Simple Data Service (Avoar SDS)

        logger.info("Downloading federal deputies history from Simple Data Service")
        sds_federal_deputies_history.get_meta_files_or_download("json", "application/json")
        logger.info("end\n\n")

        logger.info("Downloading municipalities centroid from Simple Data Service")
        sds_municipalities_centroid.get_meta_files_or_download("json", "application/json")
        logger.info("end\n\n")

        logger.info("Downloading federal deputies detailed data from Simple Data Service")
        sds_federal_deputies_detailed.get_meta_files_or_download("json", "application/json")
        logger.info("end\n\n")

        logger.info("Downloading CEAPs from câmara dos deputados")
        cd_ceaps.get_meta_files_or_download("zip", "application/zip")
        logger.info("end\n\n")

        # Governo Federal (GOV)

        logger.info("Downloading parliamentarian amendments from GOV")
        gov_amendments.get_meta_files_or_download("zip", "application/zip")
        gov_municipalities.get_meta_files_or_download("csv", 'text/csv')
        logger.info("end\n\n")

        # Receita Federal
        logger.info("Downloading data from Receita Federal")
        #receitafederal_cnaes.get_meta_files_or_download("zip", "application/zip")
        #receitafederal_empresas.get_meta_files_or_download("zip", "application/zip")
        #receitafederal_estabelecimentos.get_meta_files_or_download("zip", "application/zip")
        #receitafederal_socios.get_meta_files_or_download("zip", "application/zip")
        logger.info("end\n\n")

        logger.info("Downloading IBGE addresses data")
        #ibge_enderecos.get_meta_files_or_download("zip", "application/zip")
        logger.info("end\n\n")
