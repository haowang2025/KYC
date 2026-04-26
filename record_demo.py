import os
import sys
import time
import subprocess
import platform
import random

def clear_screen():
    os.system('cls' if platform.system() == 'Windows' else 'clear')

def type_text(text):
    """Simulate human typing with realistic pauses and hesitations."""
    for char in text:
        sys.stdout.write(char)
        sys.stdout.flush()

        delay = random.uniform(0.04, 0.12)
        if char in [' ', '"', '-', '=']:
            delay += random.uniform(0.1, 0.3)
        if random.random() < 0.08:
            delay += random.uniform(0.2, 0.5)
        time.sleep(delay)

    time.sleep(random.uniform(1.2, 2.2))
    print()

def run_command(command):
    """Run the command and stream output."""
    process = subprocess.Popen(
        command,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        encoding='utf-8',
        errors='replace'
    )
    for line in process.stdout:
        sys.stdout.write(line)
        sys.stdout.flush()
        time.sleep(0.01)
    process.wait()

def main():
    cases = [
        {
            "title": "CASE 1: Natural Language — Sanctioned Iranian Bank",
            "cmd": 'python server.py "We need to onboard Parsian Bank, an Iranian supplier, for a payment processing deal"'
        },
        {
            "title": "CASE 2: Natural Language — Clean US Company",
            "cmd": 'python server.py "Quick check on Stripe Inc from the United States, standard merchant onboarding"'
        },
        {
            "title": "CASE 3: Natural Language — Ambiguous UAE Trader (Chinese input)",
            "cmd": 'python server.py "我们要接入一家迪拜的Golden Star Trading，20万美金的电子元器件订单"'
        },
    ]

    print("🎥 ClearCheck Demo Recorder")
    print("-----------------------------------")
    print("1. Start screen recording (Win + Alt + R, or OBS, or Loom)")
    print("2. Maximize terminal window")
    print("3. Press ENTER to begin\n")
    input("Press ENTER when ready...")

    for i, case in enumerate(cases):
        clear_screen()
        time.sleep(0.5)

        # Simulated prompt
        sys.stdout.write("PS C:\\clearcheck-agent> ")
        sys.stdout.flush()

        time.sleep(random.uniform(1.2, 2.5))
        type_text(case["cmd"])

        run_command(case["cmd"])

        if i < len(cases) - 1:
            print("\n" + "="*60)
            input("Press ENTER for next case...")

    print("\n✅ Demo finished! Stop recording now.")

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding='utf-8')
    main()
