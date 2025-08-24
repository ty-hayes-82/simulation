export const secondsSince7amToClock = (totalSeconds: number): string => {
  if (!Number.isFinite(totalSeconds) || totalSeconds < 0) return '--:--';
  const total = Math.floor(totalSeconds);
  const hoursSinceStart = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const hour24 = (7 + hoursSinceStart) % 24;
  const period = hour24 >= 12 ? 'PM' : 'AM';
  let hour12 = hour24 % 12;
  if (hour12 === 0) hour12 = 12; // 12 AM or 12 PM
  return `${hour12}:${minutes.toString().padStart(2, '0')} ${period}`;
};
