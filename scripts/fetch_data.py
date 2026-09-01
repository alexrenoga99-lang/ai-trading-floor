"""
Descarga datos historicos de Dukascopy usando la libreria no oficial 'duka'.

Uso:
    python scripts/fetch_data.py --instrument USA100IDXUSD --start 2022-01-01 --end 2024-12-31 --timeframe m1 --out data/nas100

Nota: el ticker exacto de NAS100 en Dukascopy puede variar. Si falla,
probar variantes como 'USA100IDXUSD', 'USTECIDXUSD', etc.
"""
import argparse

from duka.duka import Downloader


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--instrument", required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--timeframe", default="m1")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    Downloader(
        instrument=args.instrument,
        start_date=args.start,
        end_date=args.end,
        timeframe=args.timeframe,
    ).download(save_path=args.out)

    print(f"Descarga completa en {args.out}")


if __name__ == "__main__":
    main()
