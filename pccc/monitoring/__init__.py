"""Monitoramento de hardware e sistema com dados reais do Windows.

Fontes usadas:
* psutil              — CPU, memória, discos, rede, processos
* PDH (contadores)    — GPU, frequência real da CPU, memória confirmada, atividade de disco
* DXGI                — nomes, LUID e VRAM total das placas de vídeo
* WMI                 — discos físicos e sensores (LibreHardwareMonitor / ACPI)
* nvidia-smi          — temperatura de GPUs NVIDIA (quando instalada)
"""
