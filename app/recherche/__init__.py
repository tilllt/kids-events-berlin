"""Schul-Recherche (Change 010): LLM-gestützte Terminsuche außerhalb der
Event-Pipeline.

Trennung in drei Teile, damit jeder Teil ohne Netz testbar ist:
  llm.py    — OpenAI-kompatibler Endpunkt (im Admin konfigurierbar)
  fetch.py  — Seiten holen, Text normalisieren, Termin-Fenster bilden
  kern.py   — Ablauf: Kandidaten, Vorfilter, LLM, Belegprüfung, Queue
"""
