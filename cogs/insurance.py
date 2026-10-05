"""Dravia State Bot - Insurance & Insolvency

Tables: `insurance_policies`, `insurance_claims`, `bankruptcies`. Citizens
buy fixed-tier policies, file claims, and the Insurance Company role adjudicates
them. Debtors may file for bankruptcy, which the Company settles. Dates render
through `stamp()`.
"""
import discord
from discord import app_commands

from config import COLOR_GOLD
from utils.calendar import stamp
from utils.cog import DraviaEmbed, DraviaCog, handles_validation, log_action, now, ovi, success, warning
from utils.checks import requires_insurance_company
from utils.validation import amount as validate_amount
from utils.validation import text

#: policy_type -> (premium, coverage). Fixed tiers keep the market honest.
POLICY_TIERS = {
    "Health": (300, 2000),
    "Property": (500, 5000),
    "Vehicle": (400, 3500),
    "Life": (1000, 15000),
}


class Insurance(DraviaCog):
    """Insurance Authority commands."""

    group_name = "economy"
    insurance_group = app_commands.Group(
        name="insurance", description="Policies, claims and insolvency"
    )

    # ------------------------------------------------------------ helpers
    async def _get_policy(self, policy_id: int):
        async with await self.db.get_connection() as db:
            async with db.execute(
                "SELECT policy_id, user_id, policy_type, premium, coverage, started_at, status "
                "FROM insurance_policies WHERE policy_id = ?", (policy_id,)
            ) as cur:
                row = await cur.fetchone()
        return row if row else None

    async def _get_claim(self, claim_id: int):
        async with await self.db.get_connection() as db:
            async with db.execute(
                "SELECT claim_id, policy_id, user_id, reason, amount_requested, "
                "amount_paid, status, filed_at FROM insurance_claims WHERE claim_id = ?",
                (claim_id,),
            ) as cur:
                row = await cur.fetchone()
        return row if row else None

    # ------------------------------------------------------------ commands
    @insurance_group.command(name="buy", description="Buy a policy (premium is charged now)")
    @app_commands.describe(policy_type="Cover to buy")
    @app_commands.choices(policy_type=[app_commands.Choice(name=f"{k} ({v[0]:,} Ovi → {v[1]:,} Ovi)",
                                                           value=k)
                                       for k, v in POLICY_TIERS.items()])
    async def insurance_buy(self, interaction: discord.Interaction, policy_type: str):
        if policy_type not in POLICY_TIERS:
            await self.fail(interaction, f"Unknown policy type **{policy_type}**.")
            return
        premium, coverage = POLICY_TIERS[policy_type]
        user_id = str(interaction.user.id)
        async with await self.db.get_connection() as db:
            async with db.execute(
                "SELECT 1 FROM insurance_policies WHERE user_id = ? AND policy_type = ? "
                "AND status = 'active'",
                (user_id, policy_type),
            ) as cur:
                if await cur.fetchone():
                    await self.fail(interaction, f"You already hold active **{policy_type}** cover.")
                    return
            if not await self.debit(user_id, premium, "insurance",
                                    f"{policy_type} premium"):
                await self.fail(interaction,
                                f"The **{policy_type}** premium is {ovi(premium)} — you cannot afford it.")
                return
            await db.execute(
                "INSERT INTO insurance_policies (user_id, policy_type, premium, coverage, "
                "started_at, status) VALUES (?, ?, ?, ?, date('now'), 'active')",
                (user_id, policy_type, premium, coverage),
            )
            await db.commit()
            async with db.execute(
                "SELECT MAX(policy_id) FROM insurance_policies WHERE user_id = ?",
                (user_id,),
            ) as cur:
                policy_id = (await cur.fetchone())[0]
        log_action("insurance", "buy", user_id, policy=policy_id, policy_type=policy_type)
        embed = success("Policy bound", f"**{policy_type}** cover is active.")
        embed.add_field(name="Policy ID", value=f"#{policy_id}")
        embed.add_field(name="Premium", value=f"{ovi(premium)} per term")
        embed.add_field(name="Coverage", value=ovi(coverage))
        embed.set_footer(text="File claims with /insurance claim")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @insurance_group.command(name="policies", description="Your policies")
    async def insurance_policies(self, interaction: discord.Interaction):
        async with await self.db.get_connection() as db:
            async with db.execute(
                "SELECT policy_id, policy_type, premium, coverage, started_at, status "
                "FROM insurance_policies WHERE user_id = ? ORDER BY policy_id DESC LIMIT 12",
                (str(interaction.user.id),),
            ) as cur:
                rows = await cur.fetchall()
        embed = DraviaEmbed(title="🛡️ Your Policies", color=COLOR_GOLD)
        if not rows:
            embed.description = "You hold no cover. `/insurance buy` starts a policy."
        for policy_id, policy_type, premium, coverage, started_at, status in rows:
            embed.add_field(
                name=f"#{policy_id} {policy_type}",
                value=f"**{status}** · {premium:,} Ovi → {coverage:,} Ovi · "
                      f"bound {stamp(started_at) if started_at else '—'}",
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @insurance_group.command(name="claim", description="File a claim against your policy")
    @app_commands.describe(policy_id="Policy to claim on", reason="What happened",
                           ovi_amount="Ovi you are claiming")
    @handles_validation
    async def insurance_claim(self, interaction: discord.Interaction, policy_id: int,
                              reason: str, ovi_amount: int):
        policy = await self._get_policy(policy_id)
        if policy is None:
            await self.fail(interaction, f"No policy #{policy_id} exists.")
            return
        if policy[1] != str(interaction.user.id):
            await self.fail(interaction, "That policy does not belong to you.")
            return
        if policy[6] != "active":
            await self.fail(interaction, f"Policy #{policy_id} is **{policy[6]}**.")
            return
        reason = text(reason, field="Reason", maximum=200)
        ovi_amount = validate_amount(ovi_amount, field="Claim", minimum=1,
                                     maximum=policy[4])
        async with await self.db.get_connection() as db:
            async with db.execute(
                "SELECT 1 FROM insurance_claims WHERE policy_id = ? AND status = 'filed'",
                (policy_id,),
            ) as cur:
                if await cur.fetchone():
                    await self.fail(interaction,
                                    f"Policy #{policy_id} already has a claim awaiting review.")
                    return
            await db.execute(
                "INSERT INTO insurance_claims (policy_id, user_id, reason, amount_requested, "
                "amount_paid, status, filed_at) VALUES (?, ?, ?, ?, 0, 'filed', ?)",
                (policy_id, str(interaction.user.id), reason, ovi_amount, now()),
            )
            await db.commit()
            async with db.execute("SELECT MAX(claim_id) FROM insurance_claims") as cur:
                claim_id = (await cur.fetchone())[0]
        log_action("insurance", "claim", str(interaction.user.id),
                   claim=claim_id, amount=ovi_amount)
        embed = success("Claim filed", f"Claim #{claim_id} for {ovi(ovi_amount)} is under review.")
        embed.add_field(name="Reason", value=reason)
        embed.add_field(name="Cover limit", value=ovi(policy[4]))
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @insurance_group.command(name="claims", description="Claims awaiting adjudication (Company)")
    @requires_insurance_company
    async def insurance_claims(self, interaction: discord.Interaction):
        async with await self.db.get_connection() as db:
            async with db.execute(
                "SELECT claim_id, policy_id, user_id, reason, amount_requested "
                "FROM insurance_claims WHERE status = 'filed' ORDER BY claim_id LIMIT 15"
            ) as cur:
                rows = await cur.fetchall()
        embed = DraviaEmbed(title="🛡️ Claims Queue", color=COLOR_GOLD)
        if not rows:
            embed.description = "No claims awaiting review."
        for claim_id, policy_id, user_id, reason, requested in rows:
            embed.add_field(name=f"#{claim_id} policy #{policy_id} — {ovi(requested)}",
                            value=f"<@{user_id}> · {reason}")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @insurance_group.command(name="approve", description="Pay out a claim (Company)")
    @app_commands.describe(claim_id="Claim to pay")
    @requires_insurance_company
    async def insurance_approve(self, interaction: discord.Interaction, claim_id: int):
        claim = await self._get_claim(claim_id)
        if claim is None:
            await self.fail(interaction, f"No claim #{claim_id} exists.")
            return
        if claim[6] != "filed":
            await self.fail(interaction, f"Claim #{claim_id} is **{claim[6]}**.")
            return
        policy = await self._get_policy(claim[1])
        coverage = policy[4] if policy else claim[4]
        payout = min(claim[4], coverage)
        async with await self.db.get_connection() as db:
            cur = await db.execute(
                "UPDATE insurance_claims SET status = 'approved', amount_paid = ? "
                "WHERE claim_id = ? AND status = 'filed'",
                (payout, claim_id),
            )
            changed = cur.rowcount
            await db.commit()
        if changed != 1:
            await self.fail(interaction, f"Claim #{claim_id} was just adjudicated by someone else.")
            return
        await self.credit(claim[2], payout, "insurance", f"Claim #{claim_id} approved")
        log_action("insurance", "approve", str(interaction.user.id),
                   claim=claim_id, payout=payout)
        embed = success("Claim paid", f"Claim #{claim_id}: {ovi(payout)} to <@{claim[2]}>.")
        embed.add_field(name="Requested", value=ovi(claim[4]))
        embed.add_field(name="Cover limit", value=ovi(coverage))
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @insurance_group.command(name="deny", description="Refuse a claim (Company)")
    @app_commands.describe(claim_id="Claim to refuse")
    @requires_insurance_company
    async def insurance_deny(self, interaction: discord.Interaction, claim_id: int):
        claim = await self._get_claim(claim_id)
        if claim is None:
            await self.fail(interaction, f"No claim #{claim_id} exists.")
            return
        if claim[6] != "filed":
            await self.fail(interaction, f"Claim #{claim_id} is **{claim[6]}**.")
            return
        async with await self.db.get_connection() as db:
            cur = await db.execute(
                "UPDATE insurance_claims SET status = 'denied' WHERE claim_id = ? "
                "AND status = 'filed'",
                (claim_id,),
            )
            changed = cur.rowcount
            await db.commit()
        if changed != 1:
            await self.fail(interaction, f"Claim #{claim_id} was just adjudicated by someone else.")
            return
        log_action("insurance", "deny", str(interaction.user.id), claim=claim_id)
        embed = warning("Claim refused", f"Claim #{claim_id} has been denied.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @insurance_group.command(name="cancel", description="Cancel one of your policies")
    @app_commands.describe(policy_id="Policy to cancel")
    async def insurance_cancel(self, interaction: discord.Interaction, policy_id: int):
        policy = await self._get_policy(policy_id)
        if policy is None:
            await self.fail(interaction, f"No policy #{policy_id} exists.")
            return
        if policy[1] != str(interaction.user.id):
            await self.fail(interaction, "That policy does not belong to you.")
            return
        if policy[6] != "active":
            await self.fail(interaction, f"Policy #{policy_id} is already **{policy[6]}**.")
            return
        async with await self.db.get_connection() as db:
            await db.execute("UPDATE insurance_policies SET status = 'cancelled' "
                             "WHERE policy_id = ?", (policy_id,))
            await db.commit()
        log_action("insurance", "cancel", str(interaction.user.id), policy=policy_id)
        embed = warning("Policy cancelled", f"**{policy[2]}** cover has ended.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @insurance_group.command(name="bankrupt", description="File for bankruptcy")
    @app_commands.describe(total_debt="What you owe", total_assets="What you hold")
    @handles_validation
    async def insurance_bankrupt(self, interaction: discord.Interaction,
                                 total_debt: int, total_assets: int):
        total_debt = validate_amount(total_debt, field="Debt", minimum=0, maximum=100_000_000)
        total_assets = validate_amount(total_assets, field="Assets", minimum=0,
                                       maximum=100_000_000)
        user_id = str(interaction.user.id)
        async with await self.db.get_connection() as db:
            async with db.execute(
                "SELECT 1 FROM bankruptcies WHERE user_id = ? AND status = 'filed'",
                (user_id,),
            ) as cur:
                if await cur.fetchone():
                    await self.fail(interaction, "You already have an open bankruptcy case.")
                    return
            await db.execute(
                "INSERT INTO bankruptcies (user_id, total_debt, total_assets, status, filed_at) "
                "VALUES (?, ?, ?, 'filed', ?)",
                (user_id, total_debt, total_assets, now()),
            )
            await db.commit()
            async with db.execute("SELECT MAX(case_id) FROM bankruptcies") as cur:
                case_id = (await cur.fetchone())[0]
        solvency = "insolvent" if total_debt > total_assets else "solvent"
        log_action("insurance", "bankrupt", user_id, case=case_id, debt=total_debt)
        embed = warning("Case filed",
                        f"Case #{case_id} opened — you are declared **{solvency}**.")
        embed.add_field(name="Debt", value=ovi(total_debt))
        embed.add_field(name="Assets", value=ovi(total_assets))
        embed.add_field(name="Next", value="The Insurance Company settles it with `/insurance settle`.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @insurance_group.command(name="cases", description="Open bankruptcy cases (Company)")
    @requires_insurance_company
    async def insurance_cases(self, interaction: discord.Interaction):
        async with await self.db.get_connection() as db:
            async with db.execute(
                "SELECT case_id, user_id, total_debt, total_assets, filed_at "
                "FROM bankruptcies WHERE status = 'filed' ORDER BY case_id LIMIT 15"
            ) as cur:
                rows = await cur.fetchall()
        embed = DraviaEmbed(title="🛡️ Bankruptcy Court", color=COLOR_GOLD)
        if not rows:
            embed.description = "No open cases."
        for case_id, user_id, debt, assets, filed_at in rows:
            embed.add_field(name=f"#{case_id} — <@{user_id}>",
                            value=f"debt {debt:,} vs assets {assets:,} · filed "
                                  f"{stamp(filed_at) if filed_at else '—'}")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @insurance_group.command(name="settle", description="Close a bankruptcy case (Company)")
    @app_commands.describe(case_id="Case to settle",
                           outcome="Court ruling")
    @app_commands.choices(outcome=[
        app_commands.Choice(name="Debts wiped (insolvency proven)", value="discharged"),
        app_commands.Choice(name="Payment plan imposed", value="restructured"),
        app_commands.Choice(name="Case dismissed", value="dismissed"),
    ])
    @requires_insurance_company
    async def insurance_settle(self, interaction: discord.Interaction, case_id: int,
                               outcome: str = "restructured"):
        allowed = {"discharged", "restructured", "dismissed"}
        outcome = outcome if outcome in allowed else "restructured"
        async with await self.db.get_connection() as db:
            cur = await db.execute(
                "UPDATE bankruptcies SET status = ?, closed_at = ? WHERE case_id = ? "
                "AND status = 'filed'",
                (outcome, now(), case_id),
            )
            changed = cur.rowcount
            await db.commit()
        if changed != 1:
            await self.fail(interaction, f"No open case #{case_id} exists.")
            return
        log_action("insurance", "settle", str(interaction.user.id),
                   case=case_id, outcome=outcome)
        embed = success("Case settled", f"Case #{case_id} ruled **{outcome}**.")
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot):
    """Setup function for the cog."""
    await bot.add_cog(Insurance(bot))
