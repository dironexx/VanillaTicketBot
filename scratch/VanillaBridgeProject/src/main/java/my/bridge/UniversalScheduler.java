package my.bridge;

import org.bukkit.Bukkit;
import org.bukkit.entity.Entity;
import org.bukkit.plugin.Plugin;

import java.lang.reflect.Method;
import java.util.concurrent.TimeUnit;

/**
 * Universal Scheduler for Paper, Purpur, Spigot, and Folia / Leaf (Threaded Regions).
 * Automatically delegates to Region/Async schedulers on Folia, and BukkitScheduler on standard Paper.
 */
public final class UniversalScheduler {

    private static final boolean IS_FOLIA;

    static {
        boolean folia = false;
        try {
            Class.forName("io.papermc.paper.threadedregions.RegionizedServer");
            folia = true;
        } catch (ClassNotFoundException ignored) {
        }
        IS_FOLIA = folia;
    }

    private UniversalScheduler() {}

    public static boolean isFolia() {
        return IS_FOLIA;
    }

    public interface TaskHandle {
        void cancel();
        boolean isCancelled();
    }

    public static TaskHandle runAsync(Plugin plugin, Runnable task) {
        if (IS_FOLIA) {
            var st = Bukkit.getAsyncScheduler().runNow(plugin, scheduledTask -> task.run());
            return new TaskHandle() {
                @Override
                public void cancel() {
                    st.cancel();
                }

                @Override
                public boolean isCancelled() {
                    return st.isCancelled();
                }
            };
        } else {
            var bt = Bukkit.getScheduler().runTaskAsynchronously(plugin, task);
            return new TaskHandle() {
                @Override
                public void cancel() {
                    bt.cancel();
                }

                @Override
                public boolean isCancelled() {
                    return bt.isCancelled();
                }
            };
        }
    }

    public static TaskHandle runAsyncLater(Plugin plugin, Runnable task, long delayTicks) {
        if (IS_FOLIA) {
            long delayMs = Math.max(1L, delayTicks) * 50L;
            var st = Bukkit.getAsyncScheduler().runDelayed(plugin, scheduledTask -> task.run(), delayMs, TimeUnit.MILLISECONDS);
            return new TaskHandle() {
                @Override
                public void cancel() {
                    st.cancel();
                }

                @Override
                public boolean isCancelled() {
                    return st.isCancelled();
                }
            };
        } else {
            var bt = Bukkit.getScheduler().runTaskLaterAsynchronously(plugin, task, delayTicks);
            return new TaskHandle() {
                @Override
                public void cancel() {
                    bt.cancel();
                }

                @Override
                public boolean isCancelled() {
                    return bt.isCancelled();
                }
            };
        }
    }

    public static TaskHandle runAsyncTimer(Plugin plugin, Runnable task, long delayTicks, long periodTicks) {
        if (IS_FOLIA) {
            long delayMs = Math.max(1L, delayTicks) * 50L;
            long periodMs = Math.max(1L, periodTicks) * 50L;
            var st = Bukkit.getAsyncScheduler().runAtFixedRate(plugin, scheduledTask -> task.run(), delayMs, periodMs, TimeUnit.MILLISECONDS);
            return new TaskHandle() {
                @Override
                public void cancel() {
                    st.cancel();
                }

                @Override
                public boolean isCancelled() {
                    return st.isCancelled();
                }
            };
        } else {
            var bt = Bukkit.getScheduler().runTaskTimerAsynchronously(plugin, task, delayTicks, periodTicks);
            return new TaskHandle() {
                @Override
                public void cancel() {
                    bt.cancel();
                }

                @Override
                public boolean isCancelled() {
                    return bt.isCancelled();
                }
            };
        }
    }

    public static TaskHandle runGlobal(Plugin plugin, Runnable task) {
        if (IS_FOLIA) {
            var st = Bukkit.getGlobalRegionScheduler().run(plugin, scheduledTask -> task.run());
            return new TaskHandle() {
                @Override
                public void cancel() {
                    st.cancel();
                }

                @Override
                public boolean isCancelled() {
                    return st.isCancelled();
                }
            };
        } else {
            var bt = Bukkit.getScheduler().runTask(plugin, task);
            return new TaskHandle() {
                @Override
                public void cancel() {
                    bt.cancel();
                }

                @Override
                public boolean isCancelled() {
                    return bt.isCancelled();
                }
            };
        }
    }

    public static TaskHandle runGlobalLater(Plugin plugin, Runnable task, long delayTicks) {
        if (IS_FOLIA) {
            var st = Bukkit.getGlobalRegionScheduler().runDelayed(plugin, scheduledTask -> task.run(), Math.max(1L, delayTicks));
            return new TaskHandle() {
                @Override
                public void cancel() {
                    st.cancel();
                }

                @Override
                public boolean isCancelled() {
                    return st.isCancelled();
                }
            };
        } else {
            var bt = Bukkit.getScheduler().runTaskLater(plugin, task, delayTicks);
            return new TaskHandle() {
                @Override
                public void cancel() {
                    bt.cancel();
                }

                @Override
                public boolean isCancelled() {
                    return bt.isCancelled();
                }
            };
        }
    }

    public static TaskHandle runGlobalTimer(Plugin plugin, Runnable task, long delayTicks, long periodTicks) {
        if (IS_FOLIA) {
            var st = Bukkit.getGlobalRegionScheduler().runAtFixedRate(plugin, scheduledTask -> task.run(), Math.max(1L, delayTicks), Math.max(1L, periodTicks));
            return new TaskHandle() {
                @Override
                public void cancel() {
                    st.cancel();
                }

                @Override
                public boolean isCancelled() {
                    return st.isCancelled();
                }
            };
        } else {
            var bt = Bukkit.getScheduler().runTaskTimer(plugin, task, delayTicks, periodTicks);
            return new TaskHandle() {
                @Override
                public void cancel() {
                    bt.cancel();
                }

                @Override
                public boolean isCancelled() {
                    return bt.isCancelled();
                }
            };
        }
    }

    public static TaskHandle runEntity(Plugin plugin, Entity entity, Runnable task) {
        if (entity == null) {
            return runGlobal(plugin, task);
        }
        if (IS_FOLIA) {
            var st = entity.getScheduler().run(plugin, scheduledTask -> task.run(), null);
            return new TaskHandle() {
                @Override
                public void cancel() {
                    if (st != null) st.cancel();
                }

                @Override
                public boolean isCancelled() {
                    return st == null || st.isCancelled();
                }
            };
        } else {
            var bt = Bukkit.getScheduler().runTask(plugin, task);
            return new TaskHandle() {
                @Override
                public void cancel() {
                    bt.cancel();
                }

                @Override
                public boolean isCancelled() {
                    return bt.isCancelled();
                }
            };
        }
    }

    public static TaskHandle runEntityLater(Plugin plugin, Entity entity, Runnable task, long delayTicks) {
        if (entity == null) {
            return runGlobalLater(plugin, task, delayTicks);
        }
        if (IS_FOLIA) {
            var st = entity.getScheduler().runDelayed(plugin, scheduledTask -> task.run(), null, Math.max(1L, delayTicks));
            return new TaskHandle() {
                @Override
                public void cancel() {
                    if (st != null) st.cancel();
                }

                @Override
                public boolean isCancelled() {
                    return st == null || st.isCancelled();
                }
            };
        } else {
            var bt = Bukkit.getScheduler().runTaskLater(plugin, task, delayTicks);
            return new TaskHandle() {
                @Override
                public void cancel() {
                    bt.cancel();
                }

                @Override
                public boolean isCancelled() {
                    return bt.isCancelled();
                }
            };
        }
    }

    /**
     * Safely retrieves TPS without throwing UnsupportedOperationException on Folia / Leaf.
     */
    public static double getTpsSafely() {
        try {
            double[] arr = Bukkit.getTPS();
            if (arr != null && arr.length > 0) {
                return Math.min(20.0, Math.max(0.0, arr[0]));
            }
        } catch (Throwable foliaEx) {
            // Leaf / Folia fallback via Spark if present
            try {
                Class<?> provider = Class.forName("me.lucko.spark.api.SparkProvider");
                Object spark = provider.getMethod("get").invoke(null);
                if (spark != null) {
                    Object tpsObj = spark.getClass().getMethod("tps").invoke(spark);
                    if (tpsObj != null) {
                        Method poll = tpsObj.getClass().getMethod("poll", Class.forName("me.lucko.spark.api.statistic.StatisticWindow$TicksPerSecond"));
                        Object window = Class.forName("me.lucko.spark.api.statistic.StatisticWindow$TicksPerSecond").getField("SECONDS_5").get(null);
                        Double tps = (Double) poll.invoke(tpsObj, window);
                        if (tps != null) {
                            return Math.min(20.0, Math.max(0.0, tps));
                        }
                    }
                }
            } catch (Throwable ignored) {}
        }
        return 20.0;
    }

    /**
     * Safely retrieves MSPT without throwing UnsupportedOperationException on Folia / Leaf.
     */
    public static double getMsptSafely() {
        try {
            return Bukkit.getAverageTickTime();
        } catch (Throwable foliaEx) {
            try {
                Class<?> provider = Class.forName("me.lucko.spark.api.SparkProvider");
                Object spark = provider.getMethod("get").invoke(null);
                if (spark != null) {
                    Object msptObj = spark.getClass().getMethod("mspt").invoke(spark);
                    if (msptObj != null) {
                        Method poll = msptObj.getClass().getMethod("poll", Class.forName("me.lucko.spark.api.statistic.StatisticWindow$MillisPerTick"));
                        Object window = Class.forName("me.lucko.spark.api.statistic.StatisticWindow$MillisPerTick").getField("SECONDS_10").get(null);
                        Double mspt = (Double) poll.invoke(msptObj, window);
                        if (mspt != null) {
                            return mspt;
                        }
                    }
                }
            } catch (Throwable ignored) {}
        }
        return 20.0;
    }
}
